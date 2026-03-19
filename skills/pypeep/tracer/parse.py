import argparse
import io
import json
import os
import sys
import threading
import types
from dataclasses import dataclass
from typing import Any, Callable, Literal, Protocol, TypeAlias

ReprResult: TypeAlias = "str | dict[str, Any]"
EventDict: TypeAlias = dict[str, Any]
TraceCallback: TypeAlias = Callable[[types.FrameType, str, Any], "TraceCallback"]


class StdoutSink(Protocol):
    def write(self, s: str) -> None: ...
    def flush(self) -> None: ...
    def drain(self) -> str: ...


@dataclass
class TraceEvent:
    event: Literal["call", "line", "return", "exception"]
    line: int
    function: str
    locals: dict[str, ReprResult]
    globals: dict[str, ReprResult]
    return_value: str | None = None
    exception: str | None = None
    stdout: str = ""
    thread: str | None = None

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
    return {k: smart_repr(v) for k, v in obj.__dict__.items() if not k.startswith("__")}


def _with_cycle_guard(obj_id: int, ref_stub: dict[str, Any], build: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    seen = _get_seen()
    if obj_id in seen:
        return ref_stub
    seen.add(obj_id)
    try:
        return build()
    finally:
        seen.discard(obj_id)


def smart_repr(v: object) -> ReprResult:
    obj_id = id(v)

    if isinstance(v, type):
        return _with_cycle_guard(
            obj_id,
            {"__id__": obj_id, "__class__": v.__name__, "__ref__": True},
            lambda: {"__id__": obj_id, "__class__": v.__name__, **_user_attrs(v)},
        )
    if isinstance(v, dict):
        return _with_cycle_guard(
            obj_id,
            {"__id__": obj_id, "__type__": "dict", "__ref__": True},
            lambda: {"__id__": obj_id, "__type__": "dict", "__entries__": {repr(k): smart_repr(val) for k, val in v.items()}},
        )
    if isinstance(v, (list, set)):
        type_name = type(v).__name__
        return _with_cycle_guard(
            obj_id,
            {"__id__": obj_id, "__type__": type_name, "__ref__": True},
            lambda: {"__id__": obj_id, "__type__": type_name, "__items__": [smart_repr(item) for item in v]},
        )
    if isinstance(v, tuple):
        return {"__id__": obj_id, "__type__": "tuple", "__items__": [smart_repr(item) for item in v]}
    if hasattr(v, "__dict__") and not isinstance(v, (types.ModuleType, types.FunctionType)):
        cls_name = type(v).__name__
        return _with_cycle_guard(
            obj_id,
            {"__id__": obj_id, "__class__": cls_name, "__ref__": True},
            lambda: {"__id__": obj_id, "__class__": cls_name, **_user_attrs(v)},
        )
    return repr(v)


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


def make_tracer(source_file: str, stdout_buf: StdoutSink, threaded: bool = False) -> tuple[TraceCallback, list[TraceEvent]]:
    events: list[TraceEvent] = []

    def trace_func(frame: types.FrameType, event: str, arg: Any) -> TraceCallback:
        # Skip stdlib/third-party frames; only trace the target file
        if frame.f_code.co_filename != source_file:
            return trace_func

        captured = stdout_buf.drain()

        record = TraceEvent(
            event=event,
            line=frame.f_lineno,
            function=frame.f_code.co_name,
            locals={
                k: smart_repr(v)
                for k, v in frame.f_locals.items()
                if not k.startswith("__")
            },
            globals={
                k: smart_repr(v)
                for k, v in frame.f_globals.items()
                if not k.startswith("__")
            },
            stdout=captured,
            thread=threading.current_thread().name if threaded else None,
        )

        if event == "return":
            record.return_value = repr(arg)
        elif event == "exception":
            record.exception = repr(arg[1])

        events.append(record)
        return trace_func

    return trace_func, events


def _base_event(ev: EventDict) -> EventDict:
    out: EventDict = {
        "event": ev["event"],
        "line": ev["line"],
        "function": ev["function"],
    }
    if ev.get("thread"):
        out["thread"] = ev["thread"]
    for key in ("return_value", "exception", "stdout"):
        if ev.get(key):
            out[key] = ev[key]
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


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Trace Python execution")
    parser.add_argument("file", nargs="?", default="examples/class_vs_instance.py")
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
    args = parser.parse_args()

    source_file = os.path.abspath(args.file)

    with open(source_file) as f:
        code = compile(f.read(), source_file, "exec")

    stdout_buf: StdoutSink = ThreadedStdoutCapture() if args.threads else StdoutCapture()
    tracer, events = make_tracer(source_file, stdout_buf, threaded=args.threads)

    globs: dict[str, Any] = {"__builtins__": __builtins__}
    old_stdout = sys.stdout
    sys.stdout = stdout_buf  # type: ignore[assignment]
    if args.threads:
        threading.settrace(tracer)
    sys.settrace(tracer)
    try:
        exec(code, globs)
    except Exception:
        pass
    finally:
        sys.settrace(None)
        if args.threads:
            threading.settrace(None)
        globs.clear()
        sys.stdout = old_stdout

    output = json.dumps(filter_events(events, args.mode), indent=2)
    sys.stdout.write(output + "\n")
    sys.stdout.flush()
    # Suppress any output from cleanup/atexit handlers triggered after tracing
    sys.stdout = open(os.devnull, "w")
