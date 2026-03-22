"""Runs parse.py on inline Python code passed via stdin.

Usage: echo 'print("hi")' | python run_snippet.py [--mode overview|locals|full]
"""
import os
import sys
import tempfile

script_dir = os.path.dirname(os.path.abspath(__file__))
fd, tmpfile = tempfile.mkstemp(suffix=".py", prefix="pypeep_")
try:
    with os.fdopen(fd, "w") as f:
        f.write(sys.stdin.read())
    os.execvp(sys.executable, [sys.executable, os.path.join(script_dir, "parse.py"), tmpfile] + sys.argv[1:])
finally:
    os.unlink(tmpfile)
