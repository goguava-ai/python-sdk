import contextlib
import logging
import signal
import threading
from .health import MultiHealthContext, get_health_server
from datetime import timedelta
from guava.agent import Agent

logger = logging.getLogger("guava.runner")

class Runner:
    def __init__(self):
        self._threads: list[threading.Thread] = []
        self._health_ctx = MultiHealthContext()
        # Set to ask every listener/campaign to stop accepting new calls and
        # drain in-flight ones.
        self._drain = threading.Event()

    def _add(self, target, args=(), kwargs={}):
        self._threads.append(threading.Thread(target=target, args=args, kwargs=kwargs, daemon=True))

    def listen_phone(self, agent: "Agent", agent_number: str) -> "Runner":
        self._add(agent._listen_inbound, kwargs={"health_ctx": self._health_ctx.create_ctx(), "agent_number": agent_number, "drain": self._drain})
        return self

    def listen_webrtc(self, agent: "Agent", webrtc_code: str | None = None) -> "Runner":
        if not webrtc_code:
            webrtc_code = agent._client.create_webrtc_agent(ttl=timedelta(hours=1))
        self._add(agent._listen_inbound, kwargs={"health_ctx": self._health_ctx.create_ctx(), "webrtc_code": webrtc_code, "drain": self._drain})
        return self

    def listen_sip(self, agent: "Agent", sip_code: str) -> "Runner":
        self._add(agent._listen_inbound, kwargs={"health_ctx": self._health_ctx.create_ctx(), "sip_code": sip_code, "drain": self._drain})
        return self

    def listen_for_wake(self, agent: "Agent") -> "Runner":
        self._add(agent.listen_for_wake)
        return self

    def attach_campaign(self, agent: "Agent", campaign_code: str) -> "Runner":
        self._add(agent._serve_campaign, kwargs={"health_ctx": self._health_ctx.create_ctx(), "campaign_code": campaign_code, "drain": self._drain})
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
        with get_health_server(self._health_ctx):
            if not self._threads:
                return

            with self._drain_on_signal() if handle_signals else contextlib.nullcontext():
                for t in self._threads:
                    t.start()

                for t in self._threads:
                    t.join()

        logger.info("All listeners stopped.")
