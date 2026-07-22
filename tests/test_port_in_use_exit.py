"""#1223: a port conflict must exit with a code the shell can recognise.

The reporter's backend died with `[Errno 10048] error while attempting to bind
on address ('127.0.0.1', 3900)` — port already taken, almost certainly by an
orphan from a previous session. uvicorn re-raised the bare OSError, Python
exited 1, and the desktop shell reported "Backend died (exit code 1)" with no
cause: the Windows wording is OS-translated (the report was in Russian), so no
English phrase in the log could be matched.

The fix is to make the signal locale-independent — a dedicated exit code that
`frontend/src-tauri/src/backend.rs` and `frontend/src/utils/backendCrash.ts`
both key off. This test pins the code and its cross-language agreement; the
matcher side is pinned in frontend/src/test/portInUseHint.test.js.
"""
from __future__ import annotations

import os
import re
import socket
import subprocess
import sys

import pytest

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_EXPECTED_EXIT = 78  # EX_CONFIG


def _read(*parts: str) -> str:
    with open(os.path.join(_REPO, *parts), encoding="utf-8") as fh:
        return fh.read()


def test_backend_declares_the_exit_code():
    src = _read("backend", "main.py")
    assert f"_EXIT_PORT_IN_USE = {_EXPECTED_EXIT}" in src


def test_rust_shell_agrees_on_the_exit_code():
    """The Rust side reads this code to distinguish a conflict from a crash —
    a silent divergence would restore the unexplained "exit code 1"."""
    src = _read("frontend", "src-tauri", "src", "backend.rs")
    match = re.search(r"pub const EXIT_PORT_IN_USE: i32 = (\d+);", src)
    assert match, "EXIT_PORT_IN_USE missing from backend.rs"
    assert int(match.group(1)) == _EXPECTED_EXIT


def test_frontend_crash_hint_agrees_on_the_exit_code():
    src = _read("frontend", "src", "utils", "backendCrash.ts")
    assert f"marker.exit_code === {_EXPECTED_EXIT}" in src


@pytest.mark.parametrize("errno", [48, 98, 10048])
def test_every_platforms_eaddrinuse_is_recognised(errno):
    """EADDRINUSE is 48 on macOS/BSD, 98 on Linux, 10048 on Windows. Matching
    the errno rather than the message is the whole point — the message is
    translated by the OS."""
    src = _read("backend", "main.py")
    match = re.search(r"if e\.errno in \(([\d, ]+)\)", src)
    assert match, "errno guard missing from main.py"
    assert str(errno) in {p.strip() for p in match.group(1).split(",")}


def test_real_bind_conflict_exits_with_the_dedicated_code(tmp_path):
    """End-to-end: hold a port, then run the same guard shape against it and
    confirm the process exits 78 rather than 1.

    Runs the guard standalone rather than booting the whole backend (a real
    boot downloads models); what's under test is the exception handling, and
    the OSError comes from a genuine bind conflict, not a mock."""
    holder = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    holder.bind(("127.0.0.1", 0))
    holder.listen(1)
    port = holder.getsockname()[1]
    try:
        script = tmp_path / "bind.py"
        script.write_text(
            "import socket, sys\n"
            "_EXIT_PORT_IN_USE = 78\n"
            "try:\n"
            "    s = socket.socket()\n"
            f"    s.bind(('127.0.0.1', {port}))\n"
            "except OSError as e:\n"
            "    if e.errno in (48, 98, 10048) or getattr(e, 'winerror', None) == 10048:\n"
            "        print(f'FATAL: port is already in use: {e}', file=sys.stderr)\n"
            "        sys.exit(_EXIT_PORT_IN_USE)\n"
            "    raise\n",
            encoding="utf-8",
        )
        proc = subprocess.run(
            [sys.executable, str(script)], capture_output=True, text=True
        )
        assert proc.returncode == _EXPECTED_EXIT, proc.stderr
        assert "already in use" in proc.stderr
    finally:
        holder.close()
