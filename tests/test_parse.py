import sys
import os
import threading
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "skills", "pypeep", "tracer"))

from parse import (
    DEFAULT_MAX_DEPTH,
    DEFAULT_MAX_ITEMS,
    DEFAULT_MAX_STR_LEN,
    TraceEvent,
    Tracer,
    StdoutCapture,
    ThreadedStdoutCapture,
    smart_repr,
    _safe_repr,
    _snap_vars,
    _user_attrs,
    _base_event,
    _changed_locals,
    filter_events,
)


def _trace(src, **kwargs):
    code = compile(src, "<test>", "exec")
    buf = StdoutCapture()
    tracer = Tracer("<test>", buf, **kwargs)
    old_stdout = sys.stdout
    sys.stdout = buf
    sys.settrace(tracer)
    try:
        exec(code, {"__builtins__": __builtins__})
    except Exception:
        pass
    finally:
        sys.settrace(None)
        sys.stdout = old_stdout
    return tracer.events


def _ev(event="line", line=1, function="f", **kwargs):
    return TraceEvent(event=event, line=line, function=function, locals={}, globals={}, **kwargs)


class TestSmartRepr(unittest.TestCase):
    def test_primitives(self):
        for v in (42, "hello", None, True, 3.14):
            self.assertEqual(smart_repr(v), repr(v))

    def test_dict(self):
        r = smart_repr({"a": 1})
        self.assertEqual(r["__type__"], "dict")
        self.assertEqual(len(r["__entries__"]), 1)
        self.assertEqual(r["__entries__"][0]["key"], "'a'")
        self.assertEqual(r["__entries__"][0]["value"], "1")

    def test_list(self):
        r = smart_repr([1, 2])
        self.assertEqual(r["__type__"], "list")
        self.assertEqual(r["__items__"], ["1", "2"])

    def test_set(self):
        r = smart_repr({1})
        self.assertEqual(r["__type__"], "set")

    def test_tuple(self):
        r = smart_repr((1, 2))
        self.assertEqual(r["__type__"], "tuple")
        self.assertEqual(r["__items__"], ["1", "2"])

    def test_custom_object(self):
        class Foo:
            def __init__(self):
                self.x = 10
        r = smart_repr(Foo())
        self.assertEqual(r["__class__"], "Foo")
        self.assertEqual(r["x"], "10")

    def test_circular_reference(self):
        a = []
        a.append(a)
        r = smart_repr(a)
        self.assertTrue(r["__items__"][0]["__ref__"])

    def test_type_object(self):
        r = smart_repr(int)
        self.assertEqual(r["__class__"], "int")

    def test_module_uses_repr(self):
        import os
        self.assertIsInstance(smart_repr(os), str)

    def test_function_uses_repr(self):
        self.assertIsInstance(smart_repr(lambda: None), str)

    def test_broken_repr_in_container(self):
        class Bad:
            __slots__ = ()
            def __repr__(self):
                raise RuntimeError("nope")
        result = smart_repr(Bad())
        self.assertIn("repr failed", result)

    def test_tuple_in_recursive_graph(self):
        a = []
        t = (a,)
        a.append(t)
        r = smart_repr(t)
        self.assertEqual(r["__type__"], "tuple")


class TestSnapVars(unittest.TestCase):
    def test_filters_dunders(self):
        result = _snap_vars({"x": 1, "__name__": "mod", "__builtins__": {}})
        self.assertIn("x", result)
        self.assertNotIn("__name__", result)
        self.assertNotIn("__builtins__", result)


class TestStdoutCapture(unittest.TestCase):
    def test_write_and_drain(self):
        buf = StdoutCapture()
        buf.write("hello")
        self.assertEqual(buf.drain(), "hello")

    def test_drain_clears(self):
        buf = StdoutCapture()
        buf.write("hello")
        buf.drain()
        self.assertEqual(buf.drain(), "")

    def test_flush_noop(self):
        StdoutCapture().flush()


class TestThreadedStdoutCapture(unittest.TestCase):
    def test_write_and_drain(self):
        buf = ThreadedStdoutCapture()
        buf.write("hi")
        self.assertEqual(buf.drain(), "hi")

    def test_thread_isolation(self):
        buf = ThreadedStdoutCapture()
        results = {}

        def worker(name):
            buf.write(name)
            results[name] = buf.drain()

        t1 = threading.Thread(target=worker, args=("a",))
        t2 = threading.Thread(target=worker, args=("b",))
        t1.start()
        t1.join()
        t2.start()
        t2.join()
        self.assertEqual(results["a"], "a")
        self.assertEqual(results["b"], "b")


class TestTraceEvent(unittest.TestCase):
    def test_required_fields(self):
        d = _ev().to_dict()
        for key in ("event", "line", "function", "locals", "globals"):
            self.assertIn(key, d)

    def test_omits_empty_optionals(self):
        d = _ev().to_dict()
        for key in ("return_value", "exception", "stdout", "thread", "message"):
            self.assertNotIn(key, d)

    def test_includes_set_optionals(self):
        d = _ev(return_value="42", exception="err", stdout="out", thread="T", message="msg").to_dict()
        self.assertEqual(d["return_value"], "42")
        self.assertEqual(d["exception"], "err")
        self.assertEqual(d["stdout"], "out")
        self.assertEqual(d["thread"], "T")
        self.assertEqual(d["message"], "msg")


class TestTracer(unittest.TestCase):
    def test_basic_events(self):
        events = _trace("x = 1")
        types = [e.event for e in events]
        self.assertIn("call", types)
        self.assertIn("line", types)
        self.assertIn("return", types)

    def test_variable_capture(self):
        events = _trace("x = 42")
        self.assertTrue(any("x" in e.locals for e in events))

    def test_function_call_return(self):
        events = _trace("def f(): return 1\nf()")
        call_events = [e for e in events if e.event == "call" and e.function == "f"]
        ret_events = [e for e in events if e.event == "return" and e.function == "f"]
        self.assertEqual(len(call_events), 1)
        self.assertEqual(len(ret_events), 1)
        self.assertEqual(ret_events[0].return_value, "1")

    def test_exception_capture(self):
        events = _trace("raise ValueError('boom')")
        exc_events = [e for e in events if e.event == "exception"]
        self.assertGreater(len(exc_events), 0)
        self.assertIn("boom", exc_events[0].exception)

    def test_stdout_capture(self):
        events = _trace("print('hi')")
        has_stdout = any(e.stdout for e in events)
        self.assertTrue(has_stdout)

    def test_file_filtering(self):
        events = _trace("import os\nos.path.exists('.')")
        for e in events:
            self.assertNotIn("posixpath", e.function)

    def test_event_limit(self):
        events = _trace("x = 0\nfor _ in range(10000):\n    x += 1", max_events=5)
        self.assertEqual(events[-1].event, "limit")
        self.assertIn("event limit", events[-1].message)
        non_limit = [e for e in events if e.event != "limit"]
        self.assertEqual(len(non_limit), 5)

    def test_event_limit_zero_is_unlimited(self):
        events = _trace("x = 1\ny = 2\nz = 3", max_events=0)
        self.assertTrue(all(e.event != "limit" for e in events))

    def test_recursion_limit(self):
        events = _trace("def f(): f()\nf()", max_recursion=3, max_events=0)
        self.assertEqual(events[-1].event, "limit")
        self.assertIn("recursion limit", events[-1].message)

    def test_repeated_calls_no_false_positive(self):
        events = _trace("def f(): pass\nfor _ in range(10): f()", max_recursion=3, max_events=0)
        self.assertTrue(all(e.event != "limit" for e in events))

    def test_recursion_limit_zero_is_disabled(self):
        events = _trace("def f(n):\n    if n > 0: f(n-1)\nf(5)", max_recursion=0, max_events=0)
        self.assertTrue(all(e.event != "limit" for e in events))

    def test_same_name_different_functions_no_collision(self):
        src = "def run(): pass\nclass A:\n    def run(self): pass\nrun()\nA().run()"
        events = _trace(src, max_recursion=1, max_events=0)
        self.assertTrue(all(e.event != "limit" for e in events))

    def test_capture_globals_false(self):
        events = _trace("x = 1", capture_globals=False)
        for e in events:
            self.assertEqual(e.globals, {})

    def test_capture_globals_true(self):
        events = _trace("x = 1", capture_globals=True)
        has_globals = any(e.globals for e in events)
        self.assertTrue(has_globals)

    def test_exception_has_traceback(self):
        events = _trace("raise ValueError('boom')")
        top_level = [e for e in events if e.function == "<module>" and e.event == "exception"]
        self.assertGreater(len(top_level), 0)

    def test_safe_return_value(self):
        src = "class Bad:\n    def __repr__(self): raise RuntimeError('x')\ndef f(): return Bad()\nf()"
        events = _trace(src)
        ret = [e for e in events if e.event == "return" and e.function == "f"]
        self.assertEqual(len(ret), 1)
        self.assertIn("repr failed", ret[0].return_value)


class TestUserAttrs(unittest.TestCase):
    def test_broken_dict(self):
        class Bad:
            @property
            def __dict__(self):
                raise RuntimeError("nope")
        self.assertEqual(_user_attrs(Bad()), {})

    def test_broken_attr_repr_still_works(self):
        class BadVal:
            __slots__ = ()
            def __repr__(self):
                raise RuntimeError("boom")
        class Obj:
            pass
        obj = Obj()
        obj.x = 1
        obj.bad = BadVal()
        result = _user_attrs(obj)
        self.assertEqual(result["x"], "1")
        self.assertIn("repr failed", result["bad"])


class TestSafeRepr(unittest.TestCase):
    def test_normal(self):
        self.assertEqual(_safe_repr(42), "42")

    def test_broken_repr(self):
        class Bad:
            def __repr__(self):
                raise ValueError("boom")
        result = _safe_repr(Bad())
        self.assertIn("repr failed", result)
        self.assertIn("ValueError", result)


class TestChangedLocals(unittest.TestCase):
    def test_new_key(self):
        self.assertEqual(_changed_locals({"x": "1"}, {}), {"x": "1"})

    def test_changed_value(self):
        self.assertEqual(_changed_locals({"x": "2"}, {"x": "1"}), {"x": "2"})

    def test_unchanged(self):
        self.assertEqual(_changed_locals({"x": "1"}, {"x": "1"}), {})

    def test_removed_key_not_tracked(self):
        self.assertEqual(_changed_locals({}, {"x": "1"}), {})


class TestBaseEvent(unittest.TestCase):
    def test_required_fields(self):
        ev = {"event": "line", "line": 1, "function": "f", "locals": {}, "globals": {}}
        out = _base_event(ev)
        self.assertEqual(out, {"event": "line", "line": 1, "function": "f"})

    def test_optional_fields(self):
        ev = {"event": "line", "line": 1, "function": "f", "locals": {}, "globals": {},
              "return_value": "42", "stdout": "hi", "message": "msg"}
        out = _base_event(ev)
        self.assertEqual(out["return_value"], "42")
        self.assertEqual(out["stdout"], "hi")
        self.assertEqual(out["message"], "msg")

    def test_falsy_return_value_preserved(self):
        ev = {"event": "return", "line": 1, "function": "f", "locals": {}, "globals": {},
              "return_value": "0"}
        out = _base_event(ev)
        self.assertEqual(out["return_value"], "0")


class TestFilterEvents(unittest.TestCase):
    def _make_events(self):
        return [
            TraceEvent(event="call", line=1, function="f", locals={}, globals={}),
            TraceEvent(event="line", line=2, function="f", locals={"x": "1"}, globals={"g": "10"}),
            TraceEvent(event="line", line=3, function="f", locals={"x": "2"}, globals={"g": "10"}),
            TraceEvent(event="return", line=3, function="f", locals={"x": "2"}, globals={"g": "10"}),
        ]

    def test_full_mode(self):
        events = self._make_events()
        result = filter_events(events, "full")
        self.assertTrue(all("globals" in r for r in result))
        self.assertTrue(all("locals" in r for r in result))

    def test_locals_mode(self):
        result = filter_events(self._make_events(), "locals")
        self.assertTrue(all("locals" in r for r in result))
        self.assertTrue(all("globals" not in r for r in result))

    def test_overview_mode(self):
        result = filter_events(self._make_events(), "overview")
        self.assertTrue(all("locals" not in r for r in result))
        self.assertTrue(all("globals" not in r for r in result))
        # First line event introduces x → changed
        line_events = [r for r in result if r["event"] == "line"]
        self.assertEqual(line_events[0]["changed"], {"x": "1"})
        # Second line event changes x → changed
        self.assertEqual(line_events[1]["changed"], {"x": "2"})

    def test_limit_event_passes_through(self):
        events = [_ev(event="limit", message="stopped")]
        result = filter_events(events, "overview")
        self.assertEqual(result[0]["event"], "limit")
        self.assertEqual(result[0]["message"], "stopped")


class TestDictReprDuplicateKeys(unittest.TestCase):
    def test_duplicate_repr_keys_preserved(self):
        class K:
            def __init__(self, name):
                self.name = name
            def __repr__(self):
                return "same"
            def __hash__(self):
                return hash(self.name)
            def __eq__(self, other):
                return isinstance(other, K) and self.name == other.name
        d = {K("a"): 1, K("b"): 2}
        r = smart_repr(d)
        self.assertEqual(len(r["__entries__"]), 2)


class TestSnapVarsDefensive(unittest.TestCase):
    def test_broken_value_captured(self):
        class Bad:
            __slots__ = ()
            def __repr__(self):
                raise RuntimeError("boom")
        result = _snap_vars({"x": 1, "bad": Bad()})
        self.assertEqual(result["x"], "1")
        # smart_repr handles it via _safe_repr, so it should contain the failure message
        self.assertIn("repr failed", result["bad"])


class TestSmartReprLimits(unittest.TestCase):
    def test_max_depth(self):
        v = [0]
        for _ in range(DEFAULT_MAX_DEPTH + 5):
            v = [v]
        r = smart_repr(v)
        # Walk down to find the truncation
        node = r
        for _ in range(DEFAULT_MAX_DEPTH):
            node = node["__items__"][0]
        self.assertEqual(node, "<max depth>")

    def test_max_items_list(self):
        r = smart_repr(list(range(DEFAULT_MAX_ITEMS + 10)))
        self.assertEqual(len(r["__items__"]), DEFAULT_MAX_ITEMS)
        self.assertTrue(r["__truncated__"])

    def test_max_items_dict(self):
        r = smart_repr({i: i for i in range(DEFAULT_MAX_ITEMS + 10)})
        self.assertEqual(len(r["__entries__"]), DEFAULT_MAX_ITEMS)
        self.assertTrue(r["__truncated__"])

    def test_no_truncated_flag_when_under_limit(self):
        r = smart_repr([1, 2, 3])
        self.assertNotIn("__truncated__", r)

    def test_long_string_truncated(self):
        r = smart_repr("x" * (DEFAULT_MAX_STR_LEN + 100))
        self.assertLessEqual(len(r), DEFAULT_MAX_STR_LEN + 10)
        self.assertTrue(r.endswith("..."))


class TestTracerStopFlag(unittest.TestCase):
    def test_stop_flag_set_on_limit(self):
        events = _trace("x = 0\nfor _ in range(10000):\n    x += 1", max_events=5)
        # Verify the tracer recorded events and stopped
        self.assertEqual(events[-1].event, "limit")


if __name__ == "__main__":
    unittest.main()
