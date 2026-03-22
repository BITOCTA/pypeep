# PyPeep

![Tests](https://github.com/BITOCTA/pypeep/actions/workflows/test.yml/badge.svg)

An AI coding skill that traces Python execution step-by-step. Captures every line, variable state, function calls, exceptions, and stdout — so your AI agent can debug, explain, and verify Python code.

Try the [interactive debugger](https://artemsokh.in/projects/pypeep).

## Features

- **Step-by-step tracing** — every line of execution with full variable state via `sys.settrace()`
- **3 output modes** — `overview` (changed vars only), `locals` (all locals), `full` (locals + globals)
- **Safety limits** — event count, recursion depth, and timeout protection against infinite loops/recursion
- **Multithreading** — trace all threads with per-thread stdout capture
- **Object identity tracking** — `__id__` reveals aliasing bugs, cycle detection built-in
- **Gotcha detection** — mutable defaults, reference aliasing, late binding closures
- **Cross-platform** — works on macOS, Linux, and Windows
- **Zero dependencies** — Python stdlib only

## Installation

### Claude Code

```
/plugin marketplace add BITOCTA/pypeep
/plugin install pypeep@pypeep
```

### Cursor / Codex CLI / Gemini CLI / Other editors

PyPeep uses the [SKILL.md](https://agentskills.io/specification) standard — supported by 20+ AI editors.

Clone the skill into your editor's skills directory:

```bash
# Cursor
git clone https://github.com/BITOCTA/pypeep.git ~/.cursor/skills/pypeep

# Codex CLI
git clone https://github.com/BITOCTA/pypeep.git ~/.codex/skills/pypeep

# Gemini CLI
git clone https://github.com/BITOCTA/pypeep.git ~/.gemini/skills/pypeep

# GitHub Copilot (project-level)
git clone https://github.com/BITOCTA/pypeep.git .copilot/skills/pypeep
```

Or copy just the `skills/pypeep/` folder into your editor's skills directory.

## How It Works

Once installed, the AI agent automatically uses PyPeep when you:

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

The agent receives a JSON trace of every execution step:

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
