"""Edge wake-trigger loops: wakeword, custom wake, and button-press.

Each function runs a blocking loop on a daemon thread, waiting for its
trigger condition, then POSTing to the edge server's trigger-local-call
endpoint.  All three share the same guard pattern: acquire the trigger
lock, confirm the agent is idle, then fire.
"""

from __future__ import annotations

import logging
import select
import sys
import threading
import time
from typing import TYPE_CHECKING, Callable

import httpx

from .utils import check_response

if TYPE_CHECKING:
    from .agent import Agent

logger = logging.getLogger("guava.edge_wake")

WAKEWORD_THRESHOLD = 0.9
WAKEWORD_PATIENCE = 3
WAKEWORD_COOLDOWN = 1.5

CALL_MATERIALIZE_TIMEOUT = 30


def _fire_trigger(
    agent: Agent,
    trigger_name: str,
    trigger_url: str,
) -> None:
    """Acquire the trigger lock, guard on idle, POST the trigger.

    Returns without firing if a call is already active.  After a
    successful POST, waits up to CALL_MATERIALIZE_TIMEOUT seconds for
    the call to connect and finish.  If the call never materialises
    (WebSocket failure, server crash, etc.) the idle flag is restored
    so trigger loops don't block forever.
    """
    with agent._edge_trigger_lock:
        if not agent._edge_idle.is_set():
            return
        agent._edge_trigger = trigger_name
        agent._edge_idle.clear()
        try:
            check_response(httpx.post(
                trigger_url,
                headers=agent._client._get_headers(),
            ))
            logger.info("Call triggered by %s.", trigger_name)
        except Exception:
            logger.exception("Failed to trigger local call from %s", trigger_name)
            agent._edge_idle.set()
            return

    if agent._edge_idle.wait(timeout=CALL_MATERIALIZE_TIMEOUT):
        return

    with agent._edge_trigger_lock:
        # Only reset if _init_call never consumed the trigger.
        # If _edge_trigger is None, a call connected and is still running.
        if agent._edge_trigger is None:
            return
        logger.warning(
            "Call from %s trigger did not materialise within %ds, resetting.",
            trigger_name,
            CALL_MATERIALIZE_TIMEOUT,
        )
        agent._edge_trigger = None
        agent._edge_idle.set()


AUDIO_STALL_TIMEOUT = 10


def run_wakeword_loop(agent: Agent, trigger_url: str) -> None:
    interp = agent._wakeword_interpreter

    while True:
        agent._edge_idle.wait()
        detected = threading.Event()
        last_frame = time.monotonic()
        streak = 0
        last_detection = 0.0

        def _on_score(verifier: float, gate: float) -> None:
            nonlocal streak, last_detection, last_frame
            last_frame = time.monotonic()
            now = last_frame
            if verifier >= WAKEWORD_THRESHOLD:
                streak += 1
                if streak >= WAKEWORD_PATIENCE and (now - last_detection) > WAKEWORD_COOLDOWN:
                    logger.info("Wakeword detected (score=%.3f, streak=%d)", verifier, streak)
                    last_detection = now
                    streak = 0
                    interp.reset()
                    detected.set()
            else:
                streak = 0

        try:
            interp.listen(
                on_score=_on_score,
                threshold=999.0,
                cooldown=0.1,
                blocking=False,
            )
            stalled = False
            while not detected.wait(timeout=AUDIO_STALL_TIMEOUT):
                if time.monotonic() - last_frame > AUDIO_STALL_TIMEOUT:
                    logger.warning("No audio frames for %ds, restarting wakeword listener…", AUDIO_STALL_TIMEOUT)
                    interp.stop()
                    stalled = True
                    break
            else:
                interp.stop()
        except Exception:
            logger.exception("Wakeword listener raised an exception")
            break

        if stalled:
            continue
        _fire_trigger(agent, "wakeword", trigger_url)


def run_wake_loop(
    agent: Agent,
    trigger_url: str,
    wake_fn: Callable[[], None],
) -> None:
    while True:
        agent._edge_idle.wait()
        try:
            wake_fn()
        except Exception:
            logger.exception("Wake trigger function raised an exception")
            break

        _fire_trigger(agent, "wake", trigger_url)


def run_button_loop(
    agent: Agent,
    trigger_url: str,
    *,
    has_wakeword: bool,
) -> None:
    prompt = "Press Enter to start a call"
    if has_wakeword:
        prompt += " (or say the wakeword)"
    prompt += "...\n"
    logger.info("Listening locally. %s", prompt.strip())
    logger.info("Trigger URL: %s", trigger_url)
    sys.stdout.write(prompt)
    sys.stdout.flush()

    while True:
        try:
            ready, _, _ = select.select([sys.stdin], [], [], 1.0)
        except (ValueError, OSError):
            logger.info("stdin closed, stopping button-press trigger.")
            break
        if not ready:
            continue
        try:
            line = sys.stdin.readline()
        except EOFError:
            break
        if not line:
            break

        _fire_trigger(agent, "press_enter", trigger_url)

        sys.stdout.write(prompt)
        sys.stdout.flush()
