"""Start the private Streamlit process and public ASGI gateway together."""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import uvicorn


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
STREAMLIT_PORT = 8501


def main() -> int:
    streamlit = subprocess.Popen(
        [
            sys.executable, "-m", "streamlit", "run", "app/streamlit_app.py",
            "--server.address", "127.0.0.1", "--server.port", str(STREAMLIT_PORT),
            "--server.headless", "true",
            "--browser.gatherUsageStats", "false",
        ],
        cwd=ROOT,
    )
    try:
        uvicorn.run(
            "app.gateway:app",
            host="0.0.0.0",
            port=int(os.environ.get("PORT", "3000")),
            access_log=False,
        )
    finally:
        if streamlit.poll() is None:
            streamlit.send_signal(signal.SIGTERM)
            try:
                streamlit.wait(timeout=10)
            except subprocess.TimeoutExpired:
                streamlit.kill()
                streamlit.wait(timeout=5)
    return streamlit.returncode or 0


if __name__ == "__main__":
    raise SystemExit(main())
