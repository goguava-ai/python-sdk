import threading
from typing import TYPE_CHECKING

from guava import campaigns

if TYPE_CHECKING:
    from guava.agent import Agent


class Runner:
    def __init__(self):
        self._threads: list[threading.Thread] = []

    def _add(self, target, args=(), kwargs={}):
        self._threads.append(threading.Thread(target=target, args=args, kwargs=kwargs, daemon=True))

    def listen_phone(self, agent: "Agent", agent_number: str) -> "Runner":
        self._add(agent.listen_phone, args=(agent_number,))
        return self

    def listen_webrtc(self, agent: "Agent", webrtc_code: str | None = None) -> "Runner":
        self._add(agent.listen_webrtc, args=(webrtc_code,))
        return self

    def listen_sip(self, agent: "Agent", sip_code: str) -> "Runner":
        self._add(agent.listen_sip, args=(sip_code,))
        return self

    def attach_campaign(self, agent: "Agent", campaign: campaigns.Campaign) -> "Runner":
        self._add(agent.attach_campaign, kwargs={"campaign": campaign})
        return self

    def run(self) -> None:
        if not self._threads:
            return
        for t in self._threads:
            t.start()
        for t in self._threads:
            t.join()
