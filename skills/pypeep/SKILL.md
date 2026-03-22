---
name: pypeep
description: >-
  Use this skill when a user asks to debug a Python script that produces wrong
  output, wants to understand what code does step-by-step, asks why a variable
  has an unexpected value, or wants to verify a fix works. Also use after editing
  Python code to confirm the change behaves correctly. Traces execution via
  sys.settrace(), capturing every line executed, variable states, function
  calls/returns, exceptions, and stdout as structured JSON.
---

# PyPeep — Non-Interactive Python Debugger

Captures the full execution history of a Python program as structured JSON — every line that ran, every variable change, every function call/return, every exception with full context. Unlike pdb, no breakpoints or interaction needed: run it, get the complete timeline, analyze after the fact.

## How to run

The tracer script is located relative to this skill file:

```bash
python "{{SKILL_DIR}}/tracer/parse.py" <target_file.py> [--mode overview|locals|full] [--threads] [--max-events N] [--max-recursion N] [--timeout N]
```

### Output modes

- `--mode overview` **(default)** — compact output. Shows only variables that *changed* between steps (as `"changed"` field). Best for initial debugging and understanding flow.
- `--mode locals` — includes full `locals` at every step, but no globals. Use when you need to inspect all variable states.
- `--mode full` — includes both `locals` and `globals` at every step. Use only when globals matter (class attributes, module-level state).

**Always start with `overview`.** Escalate to `locals` or `full` only if you need more detail to answer the user's question.

### Multithreading

- `--threads` — traces all threads, not just the main thread. Each event gets a `"thread"` field with the thread name (e.g., `"MainThread"`, `"Thread-1 (worker)"`). Use when the target code spawns threads via `threading.Thread`. Stdout is captured per-thread. In overview mode, "changed" locals are tracked per-thread.

**Only use `--threads` when the code uses `threading`/`concurrent.futures`.** Without it, the output stays cleaner and smaller.

### Safety limits

- `--max-events N` — stop tracing after N events (default: 10000, 0 = unlimited)
- `--max-recursion N` — stop tracing when a function recurses beyond N depth (default: 200, 0 = disabled)
- `--timeout N` — stop execution after N seconds via SIGALRM (default: 10, 0 = disabled)
- `--max-depth N` — max nesting depth for variable repr (default: 10)
- `--max-items N` — max items per container in repr (default: 50)
- `--max-str-len N` — max string repr length (default: 200)

When a limit is hit, the tracer emits a `"limit"` event with a `"message"` field explaining what happened, then outputs all events collected so far. The traced program continues running untraced until it finishes or the timeout kills it.

**For inline code snippets:** pipe the code into the wrapper script which handles temp file creation and cleanup automatically:
```bash
python "{{SKILL_DIR}}/tracer/run_snippet.py" [--mode overview|locals|full] << 'PYEOF'
# user's code here
PYEOF
```

**Note:** The tracer has built-in safety limits (event count, recursion depth, timeout) that prevent infinite loops from hanging. You can still set the Bash tool's timeout as an extra safeguard.

## Output format

JSON array of trace events to stdout. Each event has: `event` (call/line/return/exception/limit), `line`, `function`, and optional fields: `locals`, `globals`, `changed` (overview mode), `return_value`, `exception`, `stdout`, `thread`, `message`.

### Reading the output

- **Execution order** — events appear in the order lines actually executed. Follow the sequence to see the real control flow, including branches taken, loop iterations, and function call nesting.
- **Variable timeline** — in overview mode, `changed` shows which variables changed at each step. Trace a variable across events to see exactly when and where it got its value.
- **Exception context** — `event: "exception"` includes full `locals` at the moment of failure, plus the call chain that led there.
- **Stdout mapping** — `stdout` on an event is what was printed *between the previous event and this one*. This tells you which line produced which output.
- **Object identity** — complex objects include `__id__` (Python `id()`). Same `__id__` on two variables = same object in memory. This reveals aliasing bugs (mutable defaults, shared class attributes).

Other object fields: `__type__` (collections), `__class__` (instances), `__entries__` (dict pairs), `__items__` (list/set/tuple contents), `__ref__: true` (cycle back-reference).

## Analysis checklist

After running the tracer, work through this checklist:

- [ ] **Validate output** — confirm non-empty JSON array. If empty or error, check target file for syntax errors.
- [ ] **Check for limit events** — if last event is `"limit"`, trace was truncated. Narrow scope or raise `--max-events`.
- [ ] **Trace execution flow** — follow call → line → return sequence to map what actually ran and in what order. This is the primary value.
- [ ] **Track variable changes** — use `changed` fields (overview mode) to find where variables got unexpected values. Trace a variable's timeline across events.
- [ ] **Scan for exceptions** — find `event: "exception"`. Report line, function, exception value, and the variable state at that moment.
- [ ] **Map stdout to lines** — match `stdout` fields to their source lines to explain which code produced which output.
- [ ] **Check aliasing** — compare `__id__` values. Same `__id__` = same object = mutation through one affects the other.
- [ ] **Thread analysis** (if `--threads`) — group by `thread` field. Look for shared state changing across threads.

### For large traces (>200 events)

Redirect to a file and use Read with offset/limit:
```bash
python "{{SKILL_DIR}}/tracer/parse.py" <file> --mode overview > /tmp/pypeep_output.json
```
Focus on: function call/return boundaries, exceptions, unexpected variable changes, first/last events. Summarize repetitive loops (e.g., "lines 5-8 repeated 50 times").

## Gotchas

- **Decorators and metaclasses** generate extra call/return events that obscure the actual logic. If the trace is noisy, look for the user's actual function names and skip framework internals.
- **Generator functions** show a `return` event when they `yield`, with `return_value` being the yielded value. The generator isn't actually done — it will be called again.
- **Comprehensions** (list/dict/set comps) compile to hidden functions like `<listcomp>`. These appear as separate call/return pairs in the trace.
- **Large container repr** — containers with many items get truncated by `--max-items`. If aliasing analysis needs the full structure, raise the limit.
- **Import side effects** — if the target file imports modules with side effects, those will show in the trace. Focus on events in the user's file, not stdlib internals.
- **Multiline expressions** — the tracer reports the first line of a multiline expression. The traced line may not match what the user expects for split expressions.
- **`__id__` values change between runs** — don't compare ids across separate tracer invocations. Only compare within a single trace.

## When to use this tracer

- **Wrong output** — user's code runs but produces unexpected results. Trace to find where variables diverge from expectations.
- **Explain code** — user wants to understand what code does. Trace gives the actual execution order, not what you'd guess from reading it.
- **Verify a fix** — after editing code, trace both before/after to confirm the execution path changed as intended.
- **"Why does this line do X?"** — trace to see the exact variable state when that line runs.
- **Multithreaded bugs** — use `--threads` to see actual execution interleaving across threads.
- **Python gotchas** — mutable defaults, closures, scope issues. Trace makes the surprising behavior visible.

## Example files

Test with bundled examples in `{{SKILL_DIR}}/examples/`:
- `mutable_default_init.py` — mutable default argument gotcha
- `class_vs_instance.py` — class vs instance attribute confusion
- `late_binding_closures.py` — late binding in closures
