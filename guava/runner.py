import threading
from .health import MultiHealthContext, get_health_server
from datetime import timedelta
from guava.agent import Agent

class Runner:
    def __init__(self):
        self._threads: list[threading.Thread] = []
        self._health_ctx = MultiHealthContext()

    def _add(self, target, args=(), kwargs={}):
        self._threads.append(threading.Thread(target=target, args=args, kwargs=kwargs, daemon=True))

    def listen_phone(self, agent: "Agent", agent_number: str) -> "Runner":
        self._add(agent._listen_inbound, kwargs={"health_ctx": self._health_ctx.create_ctx(), "agent_number": agent_number})
        return self

    def listen_webrtc(self, agent: "Agent", webrtc_code: str | None = None) -> "Runner":
        if not webrtc_code:
            webrtc_code = agent._client.create_webrtc_agent(ttl=timedelta(hours=1))
        self._add(agent._listen_inbound, kwargs={"health_ctx": self._health_ctx.create_ctx(), "webrtc_code": webrtc_code})
        return self

    def listen_sip(self, agent: "Agent", sip_code: str) -> "Runner":
        self._add(agent._listen_inbound, kwargs={"health_ctx": self._health_ctx.create_ctx(), "sip_code": sip_code})
        return self

    def listen_for_wake(self, agent: "Agent") -> "Runner":
        self._add(agent.listen_for_wake)
        return self

    def attach_campaign(self, agent: "Agent", campaign_code: str) -> "Runner":
        self._add(agent._serve_campaign, kwargs={"health_ctx": self._health_ctx.create_ctx(), "campaign_code": campaign_code})
        return self

    def run(self) -> None:
        with get_health_server(self._health_ctx):
            if not self._threads:
                return
            
            for t in self._threads:
                t.start()
                
            for t in self._threads:
                t.join()
