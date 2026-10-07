import contextlib
import logging
import signal
import threading
from .health import MultiHealthContext, get_health_server
from .threading_utils import create_daemon_thread
from datetime import timedelta
from typing import Any, Callable, ParamSpec, Literal
from guava.agent import Agent

P = ParamSpec("P")
RunnerState = Literal["pending", "running", "stopped"]

logger = logging.getLogger("guava.runner")


class Runner:
    def __init__(self):
        self._threads: list[threading.Thread] = []
        self._health_ctx = MultiHealthContext()

        # Set to ask every listener/campaign to stop accepting new calls and
        # drain in-flight ones.
        self._drain = threading.Event()

        self._lock = threading.Lock()
        self._state: RunnerState = "pending"

    def _add(self, target: Callable[P, Any], *args: P.args, **kwargs: P.kwargs):
        t = create_daemon_thread(target, *args, **kwargs)
        with self._lock:
            if self._state == "stopped":
                raise RuntimeError("Runner has already stopped.")
            self._threads.append(t)
            if self._state == "running":
                # Runner has already started, so we need to start this thread immediately.
                t.start()

    def listen_phone(self, agent: "Agent", agent_number: str) -> "Runner":
        self._add(
            agent._listen_inbound,
            self._health_ctx.create_ctx(),
            agent_number=agent_number,
            drain=self._drain,
        )
        return self

    def listen_webrtc(self, agent: "Agent", webrtc_code: str | None = None) -> "Runner":
        if not webrtc_code:
            webrtc_code = agent._client.create_webrtc_agent(ttl=timedelta(hours=1))
        self._add(
            agent._listen_inbound,
            self._health_ctx.create_ctx(),
            webrtc_code=webrtc_code,
            drain=self._drain,
        )
        return self

    def listen_sip(self, agent: "Agent", sip_code: str) -> "Runner":
        self._add(
            agent._listen_inbound,
            self._health_ctx.create_ctx(),
            sip_code=sip_code,
            drain=self._drain,
        )
        return self

    def listen_for_wake(self, agent: "Agent") -> "Runner":
        self._add(agent.listen_for_wake)
        return self

    def attach_campaign(self, agent: "Agent", campaign_code: str) -> "Runner":
        self._add(
            agent._serve_campaign,
            self._health_ctx.create_ctx(),
            campaign_code=campaign_code,
            drain=self._drain,
        )
        return self

    def call_phone(
        self, agent: "Agent", from_number: str, to_number: str, variables: dict[str, Any] = {}
    ) -> "Runner":
        """Place an outbound call. Safe to call from handlers while running."""
        self._add(agent.call_phone, from_number, to_number, variables=variables)
        return self

    @contextlib.contextmanager
    def _drain_on_signal(self):
        """Install SIGINT/SIGTERM handlers that trigger a graceful drain.

        The first signal starts draining; the original handlers are restored
        first so a second signal terminates the process immediately (force-exit).
        """
        # signal.signal() only works on the main thread; degrade gracefully otherwise.
        if threading.current_thread() is not threading.main_thread():
            logger.warning("Runner.run() not on the main thread; signal-based draining disabled.")
            yield
            return

        previous = {
            signal.SIGINT: signal.getsignal(signal.SIGINT),
            signal.SIGTERM: signal.getsignal(signal.SIGTERM),
        }

        def _restore():
            for sig, handler in previous.items():
                signal.signal(sig, handler)

        def _handle(signum, frame):
            _restore()  # A second signal falls through to the default (terminate).
            logger.info(
                "Received %s - draining calls. Send the signal again to terminate.",
                signal.Signals(signum).name,
            )
            self._drain.set()

        signal.signal(signal.SIGINT, _handle)
        signal.signal(signal.SIGTERM, _handle)
        try:
            yield
        finally:
            _restore()

    def run(self, handle_signals: bool = True) -> None:
        with self._lock:
            if self._state != "pending":
                raise RuntimeError("Runner.run() can only be called once.")

            # Swap state to running.
            self._state = "running"

            # Threads added after this are started by _add.
            initial = list(self._threads)

        with (
            get_health_server(self._health_ctx),
            self._drain_on_signal() if handle_signals else contextlib.nullcontext(),
        ):
            for t in initial:
                t.start()

            # Threads may be added while we join (e.g. call_phone from a handler).
            i = 0
            while True:
                with self._lock:
                    if i == len(self._threads):
                        self._state = "stopped"
                        break
                    t = self._threads[i]
                t.join()
                i += 1

        logger.info("All listeners stopped.")
