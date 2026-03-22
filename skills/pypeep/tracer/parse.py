import argparse
import io
import json
import os
import signal
import sys
import threading
import traceback
import types
from dataclasses import dataclass
from typing import Any, Callable, Literal, Protocol, TypeAlias

ReprResult: TypeAlias = "str | dict[str, Any]"
EventDict: TypeAlias = dict[str, Any]


class StdoutSink(Protocol):
    def write(self, s: str) -> None: ...
    def flush(self) -> None: ...
    def drain(self) -> str: ...


@dataclass(slots=True)
class TraceEvent:
    event: Literal["call", "line", "return", "exception", "limit"]
    line: int
    function: str
    locals: dict[str, ReprResult]
    globals: dict[str, ReprResult]
    return_value: str | None = None
    exception: str | None = None
    stdout: str = ""
    thread: str | None = None
    message: str | None = None

    def to_dict(self) -> EventDict:
        out: EventDict = {
            "event": self.event,
            "line": self.line,
            "function": self.function,
            "locals": self.locals,
            "globals": self.globals,
        }
        if self.return_value is not None:
            out["return_value"] = self.return_value
        if self.exception is not None:
            out["exception"] = self.exception
        if self.stdout:
            out["stdout"] = self.stdout
        if self.thread is not None:
            out["thread"] = self.thread
        if self.message is not None:
            out["message"] = self.message
        return out


# Thread-local to prevent cross-thread contamination during concurrent smart_repr() calls
_seen = threading.local()


def _get_seen() -> set[int]:
    try:
        return _seen.s
    except AttributeError:
        _seen.s = set()
        return _seen.s


def _user_attrs(obj: object) -> dict[str, ReprResult]:
    try:
        items = obj.__dict__.items()
    except Exception:
        return {}
    result: dict[str, ReprResult] = {}
    for k, v in items:
        if k.startswith("__"):
            continue
        try:
            result[k] = smart_repr(v)
        except Exception:
            result[k] = "<attr failed>"
    return result


def _with_cycle_guard(obj_id: int, ref_stub: dict[str, Any], build: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    seen = _get_seen()
    if obj_id in seen:
        return ref_stub
    seen.add(obj_id)
    try:
        return build()
    finally:
        seen.discard(obj_id)


def _safe_repr(v: object) -> str:
    try:
        return repr(v)
    except Exception as e:
        return f"<repr failed: {type(e).__name__}>"


DEFAULT_MAX_DEPTH = 10
DEFAULT_MAX_ITEMS = 50
DEFAULT_MAX_STR_LEN = 200

_repr_state = threading.local()


def _get_depth() -> int:
    try:
        return _repr_state.depth
    except AttributeError:
        _repr_state.depth = 0
        return 0


def _set_depth(d: int) -> None:
    _repr_state.depth = d


def _get_limits() -> tuple[int, int, int]:
    try:
        return _repr_state.max_depth, _repr_state.max_items, _repr_state.max_str_len
    except AttributeError:
        return DEFAULT_MAX_DEPTH, DEFAULT_MAX_ITEMS, DEFAULT_MAX_STR_LEN


def set_repr_limits(max_depth: int = DEFAULT_MAX_DEPTH, max_items: int = DEFAULT_MAX_ITEMS, max_str_len: int = DEFAULT_MAX_STR_LEN) -> None:
    _repr_state.max_depth = max_depth
    _repr_state.max_items = max_items
    _repr_state.max_str_len = max_str_len


def smart_repr(v: object) -> ReprResult:
    max_depth, max_items_, max_str_len_ = _get_limits()
    depth = _get_depth()
    if depth >= max_depth:
        return "<max depth>"

    obj_id = id(v)

    if isinstance(v, type):
        return _with_cycle_guard(
            obj_id,
            {"__id__": obj_id, "__class__": v.__name__, "__ref__": True},
            lambda: {"__id__": obj_id, "__class__": v.__name__, **_user_attrs(v)},
        )

    _set_depth(depth + 1)
    try:
        if isinstance(v, dict):
            items = list(v.items())
            truncated = len(items) > max_items_
            items = items[:max_items_]
            return _with_cycle_guard(
                obj_id,
                {"__id__": obj_id, "__type__": "dict", "__ref__": True},
                lambda: {
                    "__id__": obj_id, "__type__": "dict",
                    "__entries__": [{"key": smart_repr(k), "value": smart_repr(val)} for k, val in items],
                    **({"__truncated__": True} if truncated else {}),
                },
            )
        if isinstance(v, (list, set, tuple)):
            type_name = type(v).__name__
            items = list(v)
            truncated = len(items) > max_items_
            items = items[:max_items_]
            return _with_cycle_guard(
                obj_id,
                {"__id__": obj_id, "__type__": type_name, "__ref__": True},
                lambda: {
                    "__id__": obj_id, "__type__": type_name,
                    "__items__": [smart_repr(item) for item in items],
                    **({"__truncated__": True} if truncated else {}),
                },
            )
        if hasattr(v, "__dict__") and not isinstance(v, (types.ModuleType, types.FunctionType)):
            cls_name = type(v).__name__
            return _with_cycle_guard(
                obj_id,
                {"__id__": obj_id, "__class__": cls_name, "__ref__": True},
                lambda: {"__id__": obj_id, "__class__": cls_name, **_user_attrs(v)},
            )
    finally:
        _set_depth(depth)

    r = _safe_repr(v)
    if isinstance(r, str) and len(r) > max_str_len_:
        r = r[:max_str_len_] + "..."
    return r


class StdoutCapture:
    def __init__(self) -> None:
        self._buf = io.StringIO()

    def write(self, s: str) -> None:
        self._buf.write(s)

    def flush(self) -> None:
        # No-op: buffer is drained by trace_func, not flushed
        pass

    def drain(self) -> str:
        val = self._buf.getvalue()
        if val:
            self._buf.truncate(0)
            self._buf.seek(0)
        return val


class ThreadedStdoutCapture:
    def __init__(self) -> None:
        self._local = threading.local()

    def _get_buf(self) -> io.StringIO:
        try:
            return self._local.buf
        except AttributeError:
            self._local.buf = io.StringIO()
            return self._local.buf

    def write(self, s: str) -> None:
        self._get_buf().write(s)

    def flush(self) -> None:
        # No-op: each thread's buffer is drained by trace_func, not flushed
        pass

    def drain(self) -> str:
        buf = self._get_buf()
        val = buf.getvalue()
        if val:
            buf.truncate(0)
            buf.seek(0)
        return val


def _snap_vars(mapping: dict[str, Any]) -> dict[str, ReprResult]:
    result: dict[str, ReprResult] = {}
    for k, v in mapping.items():
        if k.startswith("__"):
            continue
        try:
            result[k] = smart_repr(v)
        except Exception:
            result[k] = "<snap failed>"
    return result


class Tracer:
    def __init__(
        self,
        source_file: str,
        stdout_buf: StdoutSink,
        threaded: bool = False,
        max_events: int = 10000,
        max_recursion: int = 200,
        capture_globals: bool = False,
    ) -> None:
        self.source_file = source_file
        self.stdout_buf = stdout_buf
        self.threaded = threaded
        self.max_events = max_events
        self.max_recursion = max_recursion
        self.capture_globals = capture_globals
        self.events: list[TraceEvent] = []
        self._call_depth: dict[tuple[int, int], int] = {}
        self._stopped = threading.Event()

    def _stop(self, line: int, function: str, message: str) -> None:
        self._stopped.set()
        self.events.append(TraceEvent(
            event="limit", line=line, function=function,
            locals={}, globals={}, message=message,
        ))
        sys.settrace(None)
        if self.threaded:
            threading.settrace(None)  # type: ignore[arg-type]

    def _check_limits(self, frame: types.FrameType, event: str) -> bool:
        """Return True if a limit was hit and tracing should stop."""
        fname = frame.f_code.co_name
        if self.max_events and len(self.events) >= self.max_events:
            self._stop(frame.f_lineno, fname,
                       f"Tracing stopped: event limit ({self.max_events}) reached")
            return True
        key = (threading.get_ident(), id(frame.f_code))
        if event == "call":
            self._call_depth[key] = self._call_depth.get(key, 0) + 1
            if self.max_recursion and self._call_depth[key] > self.max_recursion:
                self._stop(frame.f_lineno, fname,
                           f"Tracing stopped: recursion limit ({self.max_recursion}) reached in {fname}")
                return True
        elif event == "return" and key in self._call_depth:
            self._call_depth[key] = max(0, self._call_depth[key] - 1)
        return False

    def _local_trace(self, frame: types.FrameType, event: str, arg: Any) -> "Callable[..., Any] | None":
        if self._stopped.is_set():
            return None
        if self._check_limits(frame, event):
            return None

        record = TraceEvent(
            event=event,
            line=frame.f_lineno,
            function=frame.f_code.co_name,
            locals=_snap_vars(frame.f_locals),
            globals=_snap_vars(frame.f_globals) if self.capture_globals else {},
            stdout=self.stdout_buf.drain(),
            thread=threading.current_thread().name if self.threaded else None,
        )

        if event == "return":
            record.return_value = _safe_repr(arg)
        elif event == "exception":
            record.exception = _safe_repr(arg[1])

        self.events.append(record)
        return self._local_trace

    def __call__(self, frame: types.FrameType, event: str, arg: Any) -> "Callable[..., Any] | None":
        if self._stopped.is_set():
            return None
        if frame.f_code.co_filename != self.source_file:
            return None
        return self._local_trace(frame, event, arg)


def _base_event(ev: EventDict) -> EventDict:
    out: EventDict = {
        "event": ev["event"],
        "line": ev["line"],
        "function": ev["function"],
    }
    if ev.get("thread") is not None:
        out["thread"] = ev["thread"]
    for key in ("return_value", "exception", "message"):
        if ev.get(key) is not None:
            out[key] = ev[key]
    if ev.get("stdout"):
        out["stdout"] = ev["stdout"]
    return out


def _changed_locals(cur: dict[str, ReprResult], prev_locals: dict[str, ReprResult]) -> dict[str, ReprResult]:
    return {k: v for k, v in cur.items() if prev_locals.get(k) != v}


def filter_events(events: list[TraceEvent], mode: Literal["overview", "locals", "full"]) -> list[EventDict]:
    raw = [e.to_dict() for e in events]
    if mode == "full":
        return raw

    filtered: list[EventDict] = []
    prev_locals_by_thread: dict[str, dict[str, ReprResult]] = {}
    for ev in raw:
        out = _base_event(ev)

        if mode == "locals":
            out["locals"] = ev["locals"]
        elif mode == "overview":
            thread = ev.get("thread") or ""
            changed = _changed_locals(ev["locals"], prev_locals_by_thread.get(thread, {}))
            if changed:
                out["changed"] = changed
            prev_locals_by_thread[thread] = ev["locals"]

        filtered.append(out)
    return filtered


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Trace Python execution")
    parser.add_argument("file")
    parser.add_argument(
        "--mode",
        choices=["overview", "locals", "full"],
        default="overview",
        help="overview: compact (changed vars only), locals: include all locals, full: locals+globals",
    )
    parser.add_argument(
        "--threads",
        action="store_true",
        help="trace all threads (adds 'thread' field to events)",
    )
    parser.add_argument(
        "--max-events", type=int, default=10000,
        help="stop tracing after N events (0 = unlimited, default: 10000)",
    )
    parser.add_argument(
        "--max-recursion", type=int, default=200,
        help="stop tracing when a function recurses beyond N depth (0 = disabled, default: 200)",
    )
    parser.add_argument(
        "--timeout", type=int, default=10,
        help="stop execution after N seconds (0 = disabled, default: 10)",
    )
    parser.add_argument(
        "--max-depth", type=int, default=DEFAULT_MAX_DEPTH,
        help=f"max nesting depth for variable repr (default: {DEFAULT_MAX_DEPTH})",
    )
    parser.add_argument(
        "--max-items", type=int, default=DEFAULT_MAX_ITEMS,
        help=f"max items per container in repr (default: {DEFAULT_MAX_ITEMS})",
    )
    parser.add_argument(
        "--max-str-len", type=int, default=DEFAULT_MAX_STR_LEN,
        help=f"max string repr length (default: {DEFAULT_MAX_STR_LEN})",
    )
    return parser.parse_args()


def _timeout_handler(_signum: int, _frame: types.FrameType | None) -> None:
    raise TimeoutError("Execution timed out")


def _source_lineno(e: BaseException, source_file: str) -> int:
    lineno = 0
    tb = e.__traceback__
    while tb:
        if tb.tb_frame.f_code.co_filename == source_file:
            lineno = tb.tb_lineno
        tb = tb.tb_next
    return lineno


def _run_traced(code: types.CodeType, tracer: Tracer, source_file: str, args: argparse.Namespace) -> None:
    globs: dict[str, Any] = {
        "__builtins__": __builtins__,
        "__name__": "__main__",
        "__file__": source_file,
        "__package__": None,
    }
    old_stdout = sys.stdout
    sys.stdout = tracer.stdout_buf  # type: ignore[assignment]
    if args.threads:
        threading.settrace(tracer)
    sys.settrace(tracer)
    if args.timeout:
        signal.signal(signal.SIGALRM, _timeout_handler)
        signal.alarm(args.timeout)
    try:
        exec(code, globs)
    except TimeoutError as e:
        tracer.events.append(TraceEvent(
            event="limit", line=0, function="<timeout>",
            locals={}, globals={}, message=str(e),
        ))
    except Exception as e:
        tracer.events.append(TraceEvent(
            event="exception", line=_source_lineno(e, source_file), function="<top-level>",
            locals={}, globals={},
            exception="".join(traceback.format_exception_only(type(e), e)).strip(),
            message="".join(traceback.format_exception(type(e), e, e.__traceback__)).strip(),
        ))
    finally:
        if args.timeout:
            signal.alarm(0)
        sys.settrace(None)
        if args.threads:
            threading.settrace(None)
        globs.clear()
        sys.stdout = old_stdout


def main() -> None:
    args = _parse_args()
    source_file = os.path.abspath(args.file)

    set_repr_limits(args.max_depth, args.max_items, args.max_str_len)

    with open(source_file, encoding="utf-8") as f:
        code = compile(f.read(), source_file, "exec")

    stdout_buf: StdoutSink = ThreadedStdoutCapture() if args.threads else StdoutCapture()
    tracer = Tracer(
        source_file, stdout_buf, threaded=args.threads,
        max_events=args.max_events, max_recursion=args.max_recursion,
        capture_globals=args.mode == "full",
    )

    _run_traced(code, tracer, source_file, args)

    failed = any(
        e.event == "exception"
        or (e.event == "limit" and "event limit" not in (e.message or ""))
        for e in tracer.events
    )

    output = json.dumps(filter_events(tracer.events, args.mode), indent=2)
    sys.stdout.write(output + "\n")
    sys.stdout.flush()
    # Suppress any output from cleanup/atexit handlers triggered after tracing
    _devnull = open(os.devnull, "w")  # noqa: SIM115
    sys.stdout = _devnull

    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
