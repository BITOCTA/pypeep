# PyPeep


A Claude Code skill that traces Python execution step-by-step. Captures every line, variable state, function calls, exceptions, and stdout — so Claude can debug, explain, and verify Python code.

Try the [interactive debugger](https://artemsokh.in/projects/pypeep).

## Features

- **Step-by-step tracing** — every line of execution with full variable state via `sys.settrace()`
- **3 output modes** — `overview` (changed vars only), `locals` (all locals), `full` (locals + globals)
- **Multithreading** — trace all threads with per-thread stdout capture
- **Object identity tracking** — `__id__` reveals aliasing bugs, cycle detection built-in
- **Gotcha detection** — mutable defaults, reference aliasing, late binding closures
- **Zero dependencies** — Python stdlib only

## Installation

### Using Claude Marketplace (Claude Code)

Install in Claude Code with two commands:

```
/plugin marketplace add BITOCTA/pypeep
/plugin install pypeep@pypeep
```

## How It Works

Once installed, Claude automatically uses PyPeep when you:

- Ask to **debug** a Python script
- Ask to **explain** what code does step by step
- Ask to **verify** a fix works correctly
- Ask about **Python gotchas** (mutable defaults, closures, scope)
- Need to understand **multithreaded** execution

Just describe what you need in natural language:

```
Debug why this script prints the wrong output
Explain what this code does step by step
I fixed the bug — can you verify it works now?
Why does this function share state between calls?
```

## Output

Claude receives a JSON trace of every execution step:

```json
{
  "event": "line",
  "line": 5,
  "function": "main",
  "locals": { "x": 42 },
  "stdout": "hello\n"
}
```

Complex objects show identity (`__id__`), type, and contents — making aliasing bugs immediately visible.

## Skill Documentation

See [`skills/pypeep/SKILL.md`](skills/pypeep/SKILL.md) for full skill documentation including output format, analysis guide, and usage details.

## License

[MIT](LICENSE)
