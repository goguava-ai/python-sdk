"""Edge-only examples: speech recognition, the LLM and the voice all run on-device.

These need the `wakeword` extra and the Guava Edge runtime:

    pip install "guava-sdk[wakeword]"
    guava edge install && guava edge install models   # one-off
    python -m guava.examples.edge.plant

Importing this package starts the local guava-edge server (unless one is already running,
e.g. under `guava run --edge`) and points the SDK at it. It shuts down when Python exits.
"""

import atexit
import importlib.util
import os
import subprocess
import sys
import time
from pathlib import Path

import httpx

LOCAL_BASE_URL = "http://127.0.0.1:8080"
STARTUP_TIMEOUT = 120

# The modules the `wakeword` extra installs (see pyproject.toml).
WAKEWORD_MODULES = ("nanowakeword", "onnxruntime", "pyaudio")


def _require_wakeword_extra() -> None:
    """The examples ship in every install but only run with the `wakeword` extra."""
    missing = [m for m in WAKEWORD_MODULES if importlib.util.find_spec(m) is None]
    if missing:
        sys.exit(
            f"The edge examples need the wakeword extra (missing: {', '.join(missing)}). "
            "Install it with:\n"
            '  pip install "guava-sdk[wakeword]"'
        )


def _binary_path() -> Path:
    """Where `guava edge install` puts guava-edge (the CLI's config dir)."""
    if os.environ.get("GUAVA_BINARY"):
        return Path(os.environ["GUAVA_BINARY"])
    if sys.platform == "darwin":
        config = Path.home() / "Library" / "Application Support"
    else:
        config = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return config / ".guava" / "bin" / "guava-edge"


def _healthy() -> bool:
    try:
        return httpx.get(f"{LOCAL_BASE_URL}/healthz", timeout=2).is_success
    except httpx.HTTPError:
        return False


def _start_server() -> None:
    binary = _binary_path()
    if not binary.exists():
        sys.exit(
            f"guava-edge not found at {binary}. Install it with:\n"
            "  guava edge install && guava edge install models"
        )

    # Watchdog: guava-edge exits when its stdin hits EOF, which happens when this
    # process closes the write end, including if it's killed. Its own session keeps
    # terminal Ctrl-C away from it, so the example can shut down first.
    read_fd, write_fd = os.pipe()
    # guava-edge's embedded Python leaves a multiprocessing semaphore for its resource
    # tracker to clean up on exit; the tracker's warning about it is noise.
    warnings = ",".join(
        filter(
            None,
            [
                os.environ.get("PYTHONWARNINGS"),
                "ignore::UserWarning:multiprocessing.resource_tracker",
            ],
        )
    )
    proc = subprocess.Popen(
        [str(binary)],
        stdin=read_fd,
        env={**os.environ, "GUAVA_WATCHDOG": "1", "PYTHONWARNINGS": warnings},
        start_new_session=True,
    )
    os.close(read_fd)

    def stop() -> None:
        os.close(write_fd)
        try:
            proc.wait(timeout=3)
        except (subprocess.TimeoutExpired, KeyboardInterrupt):
            # A second Ctrl-C means "stop now", not "wait for a clean shutdown".
            proc.kill()

    atexit.register(stop)

    deadline = time.monotonic() + STARTUP_TIMEOUT
    while not _healthy():
        if proc.poll() is not None:
            sys.exit(
                f"guava-edge exited during startup (exit code {proc.returncode}); "
                "see its output above."
            )
        if time.monotonic() > deadline:
            sys.exit(
                f"guava-edge did not answer {LOCAL_BASE_URL}/healthz within {STARTUP_TIMEOUT}s."
            )
        time.sleep(0.5)


def _ensure_edge_server() -> None:
    # `guava run --edge` has already started one and set these.
    if not os.environ.get("GUAVA_EDGE"):
        if not _healthy():
            _start_server()
        os.environ.update(GUAVA_BASE_URL=LOCAL_BASE_URL, GUAVA_API_KEY="gva-edge", GUAVA_EDGE="1")


_require_wakeword_extra()
_ensure_edge_server()
