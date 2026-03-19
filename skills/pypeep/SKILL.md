---
name: pypeep
description: >-
  Traces Python program execution step-by-step using sys.settrace().
  Shows every line executed, variable states at each step, function calls/returns,
  exceptions, and stdout capture. Use to debug Python programs, verify code fixes,
  understand unfamiliar code, or detect common Python gotchas like mutable defaults
  and reference aliasing.
---

# PyPeep — Step-by-Step Python Execution Tracer

You have access to a Python tracer that captures every execution step of a Python program.
Use it to debug, test, and understand Python code.

## How to run

The tracer script is located relative to this skill file:

```bash
python "{{SKILL_DIR}}/tracer/parse.py" <target_file.py> [--mode overview|locals|full] [--threads]
```

### Output modes

- `--mode overview` **(default)** — compact output. Shows only variables that *changed* between steps (as `"changed"` field). Best for initial debugging and understanding flow.
- `--mode locals` — includes full `locals` at every step, but no globals. Use when you need to inspect all variable states.
- `--mode full` — includes both `locals` and `globals` at every step. Use only when globals matter (class attributes, module-level state).

**Always start with `overview`.** Escalate to `locals` or `full` only if you need more detail to answer the user's question.

### Multithreading

- `--threads` — traces all threads, not just the main thread. Each event gets a `"thread"` field with the thread name (e.g., `"MainThread"`, `"Thread-1 (worker)"`). Use when the target code spawns threads via `threading.Thread`. Stdout is captured per-thread. In overview mode, "changed" locals are tracked per-thread.

**Only use `--threads` when the code uses `threading`/`concurrent.futures`.** Without it, the output stays cleaner and smaller.

**For inline code snippets:** pipe the code into the wrapper script which handles temp file creation and cleanup automatically:
```bash
bash "{{SKILL_DIR}}/tracer/run_snippet.sh" [--mode overview|locals|full] << 'PYEOF'
# user's code here
PYEOF
```

**Important:** Use the Bash tool's built-in timeout (set to 30000ms) to prevent infinite loops from hanging.

## Output format

The tracer outputs a JSON array of TraceEvent objects to stdout:

```json
[
  {
    "event": "call | line | return | exception",
    "line": 14,
    "function": "add_user",
    "locals": {
      "name": "'admin'",
      "roles": {
        "__id__": 4350457280,
        "__type__": "dict",
        "__entries__": { "0": "'superuser'" }
      }
    },
    "globals": { "UserRegistry": { "__id__": 123, "__class__": "UserRegistry", ... } },
    "return_value": "None",
    "exception": "KeyError('missing')",
    "stdout": "text printed between this step and the previous one",
    "thread": "Thread-1 (only present with --threads)"
  }
]
```

### Event types
- **call** — a function was called
- **line** — a line is about to execute
- **return** — a function is returning (check `return_value`)
- **exception** — an exception was raised (check `exception`)

### Object representation
Complex objects (dicts, lists, sets, class instances) are represented as nested JSON with:
- `__id__` — Python object identity (`id()`). **Same `__id__` = same object in memory** — this reveals aliasing bugs.
- `__type__` — for built-in collections: `"dict"`, `"list"`, `"set"`, `"tuple"`
- `__class__` — for class instances: the class name
- `__entries__` — dict contents (keys are repr'd)
- `__items__` — list/set/tuple contents
- `__ref__: true` — back-reference to an already-seen object (cycle detection)

Primitive values are stored as their `repr()` string (e.g., `"'hello'"`, `"42"`, `"True"`).

## How to analyze traces

When presenting trace results to the user:

1. **Variable mutations** — look for locals/globals that change between consecutive events on the same line or function. Highlight unexpected changes.

2. **Aliasing bugs** — when two variables share the same `__id__`, they point to the same object. Mutations through one affect the other. This is the #1 Python gotcha (mutable default arguments, shared class attributes).

3. **Exceptions** — find events where `event: "exception"`. Report which line and function raised it, and the exception value.

4. **Execution flow** — trace the sequence of `call` → `line` → `return` events to show which functions were called and in what order.

5. **Stdout** — the `stdout` field captures what was printed between trace steps. Aggregate these to show the full program output.

6. **Multithreaded traces** — when `--threads` is used, group analysis by the `"thread"` field. Look for race conditions: variables shared across threads changing unexpectedly, or execution order that differs from what the code implies.

7. **For large traces (>200 events)** — use `--mode overview` (default) to keep output small. If you still need to dig deeper, redirect to a file and use Read with offset/limit:
   ```bash
   python "{{SKILL_DIR}}/tracer/parse.py" <file> --mode locals > /tmp/pypeep_output.json
   ```
   When summarizing large traces, focus on:
   - Function call/return boundaries
   - Lines where exceptions occur
   - Lines where variables change unexpectedly
   - The first and last few events
   - Summarize repetitive loops (e.g., "lines 5-8 repeated 50 times")

## When to use this tracer

- User asks to **debug** a Python script that produces wrong output
- User asks to **explain** what a piece of Python code does step by step
- You've just **edited** Python code and want to verify the fix works
- User asks about **Python gotchas** (mutable defaults, closures, scope, etc.)
- You need to understand **why** a specific line produces a certain result
- User asks to debug **multithreaded** code — use `--threads` to see all thread execution

## Example files

Test with bundled examples in `{{SKILL_DIR}}/examples/`:
- `mutable_default_init.py` — mutable default argument gotcha
- `class_vs_instance.py` — class vs instance attribute confusion
- `late_binding_closures.py` — late binding in closures
