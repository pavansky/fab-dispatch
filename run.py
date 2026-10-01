#!/usr/bin/env python3
"""Start Fab Dispatch locally with one command:  python3 run.py

Checks Python and Node, installs what's missing (once), starts the API and the UI together, and
opens the browser. Ctrl-C stops both. Works on macOS, Linux and Windows. No accounts or keys.

    python3 run.py            # set up if needed, then start
    python3 run.py --setup    # only install dependencies
    python3 run.py --no-open  # don't open a browser (e.g. in Codespaces)
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import signal
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BACKEND, FRONTEND = ROOT / "backend", ROOT / "frontend"
WIN = os.name == "nt"
VENV = BACKEND / ".venv"
PY = VENV / ("Scripts/python.exe" if WIN else "bin/python")
NPM = "npm.cmd" if WIN else "npm"
API, UI = "http://127.0.0.1:8000", "http://localhost:5173"


def say(msg: str) -> None:
    print(
        f"\033[38;5;208m▸\033[0m {msg}" if sys.stdout.isatty() else f"> {msg}",
        flush=True,
    )


def fail(msg: str) -> None:
    print(f"\n✖ {msg}", file=sys.stderr)
    sys.exit(1)


def check_tools() -> None:
    if not (3, 11) <= sys.version_info[:2] <= (3, 14):
        fail(
            f"Python 3.11–3.14 is required (this is {sys.version.split()[0]}). See the README's Troubleshooting."
        )
    if not shutil.which("node"):
        fail("Node.js 20.19+ is required: https://nodejs.org (22 LTS recommended).")
    major, minor = (
        int(x)
        for x in subprocess.check_output(["node", "-v"], text=True)
        .strip()
        .lstrip("v")
        .split(".")[:2]
    )
    if (major, minor) < (20, 19):
        fail(f"Node.js 20.19+ is required (found {major}.{minor}).")


def _stamp(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def setup() -> None:
    """Install once; re-install only when a dependency file changed."""
    reqs, marker = BACKEND / "requirements.txt", VENV / ".fab-installed"
    if not PY.exists():
        say("Creating the Python environment (backend/.venv)…")
        subprocess.check_call([sys.executable, "-m", "venv", str(VENV)])
    if not marker.exists() or marker.read_text() != _stamp(reqs):
        say("Installing Python packages (first run takes a minute)…")
        subprocess.check_call(
            [str(PY), "-m", "pip", "install", "-q", "--upgrade", "pip"]
        )
        subprocess.check_call([str(PY), "-m", "pip", "install", "-q", "-r", str(reqs)])
        marker.write_text(_stamp(reqs))
    lock, nm_marker = (
        FRONTEND / "package-lock.json",
        FRONTEND / "node_modules" / ".fab-installed",
    )
    if not nm_marker.exists() or nm_marker.read_text() != _stamp(lock):
        say("Installing UI packages…")
        subprocess.check_call(
            [NPM, "install", "--no-audit", "--no-fund", "--loglevel=error"],
            cwd=FRONTEND,
        )
        nm_marker.write_text(_stamp(lock))


def wait_for(url: str, seconds: int = 90) -> bool:
    deadline = time.time() + seconds
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2):
                return True
        except OSError:  # not listening yet (URLError, connection refused, timeout)
            time.sleep(0.5)
    return False


def start(open_browser: bool) -> None:
    say("Starting the API on :8000 and the UI on :5173…")
    flags = (
        {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
        if WIN
        else {"start_new_session": True}
    )
    procs = [
        subprocess.Popen(
            [str(PY), "-m", "uvicorn", "app.main:app", "--port", "8000"],
            cwd=BACKEND,
            **flags,
        ),
        subprocess.Popen(
            [NPM, "run", "dev", "--", "--port", "5173", "--strictPort", "--host"],
            cwd=FRONTEND,
            **flags,
        ),
    ]

    def stop(*_):
        for p in procs:
            if p.poll() is None:
                p.terminate() if WIN else os.killpg(p.pid, signal.SIGTERM)
        sys.exit(0)

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    if not wait_for(f"{API}/api/livez"):
        stop()
        fail(
            "The API didn't start. Is port 8000 free? See the README's Troubleshooting."
        )
    wait_for(UI)
    print(
        f"\n  Fab Dispatch is running.\n\n  App   {UI}   (click 'Continue as Dispatcher')\n"
        f"  API   {API}/api/docs\n\n  Press Ctrl-C to stop.\n",
        flush=True,
    )
    if open_browser:
        webbrowser.open(UI)
    while all(p.poll() is None for p in procs):
        time.sleep(1)
    stop()


def main() -> None:
    ap = argparse.ArgumentParser(description="Start Fab Dispatch locally.")
    ap.add_argument("--setup", action="store_true", help="only install dependencies")
    ap.add_argument("--no-open", action="store_true", help="don't open a browser")
    args = ap.parse_args()
    check_tools()
    setup()
    if not args.setup:
        start(open_browser=not args.no_open and not os.environ.get("CODESPACES"))


if __name__ == "__main__":
    main()
