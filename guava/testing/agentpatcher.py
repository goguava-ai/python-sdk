from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from guava.agent import Agent

# This class has to be kept in sync with the callbacks on ../agent.py
class AgentPatcher:
    _ATTRS = [
        '_on_call_received', '_on_call_start', '_on_caller_speech',
        '_on_agent_speech', '_on_question', '_on_action_requested',
        '_on_session_end', '_on_outbound_failed', '_on_escalate', '_on_dtmf',
        '_on_task_complete_generic', '_on_task_complete_handlers',
        '_on_action_generic', '_on_action_handlers', '_search_query_handlers',
    ]

    def __init__(self, agent: Agent):
        self._agent = agent
        self._saved: dict = {}

    def __enter__(self) -> AgentPatcher:
        for attr in self._ATTRS:
            val = getattr(self._agent, attr)
            self._saved[attr] = val.copy() if isinstance(val, dict) else val
        return self

    def __exit__(self, *args):
        for attr, val in self._saved.items():
            setattr(self._agent, attr, val)

    def on_call_received(self, fn=None):
        if fn is None:
            return self._agent.on_call_received()
        return self._agent.on_call_received(fn)

    def on_call_start(self, fn=None):
        if fn is None:
            return self._agent.on_call_start()
        return self._agent.on_call_start(fn)

    def on_caller_speech(self, fn=None):
        if fn is None:
            return self._agent.on_caller_speech()
        return self._agent.on_caller_speech(fn)

    def on_agent_speech(self, fn=None):
        if fn is None:
            return self._agent.on_agent_speech()
        return self._agent.on_agent_speech(fn)

    def on_question(self, fn=None):
        if fn is None:
            return self._agent.on_question()
        return self._agent.on_question(fn)

    def on_action_request(self, fn=None):
        if fn is None:
            return self._agent.on_action_request()
        return self._agent.on_action_request(fn)

    def on_session_end(self, fn=None):
        if fn is None:
            return self._agent.on_session_end()
        return self._agent.on_session_end(fn)

    def on_outbound_failed(self, fn=None):
        if fn is None:
            return self._agent.on_outbound_failed()
        return self._agent.on_outbound_failed(fn)

    def on_escalate(self, fn=None):
        if fn is None:
            return self._agent.on_escalate()
        return self._agent.on_escalate(fn)

    def on_dtmf(self, fn=None):
        if fn is None:
            return self._agent.on_dtmf()
        return self._agent.on_dtmf(fn)

    def on_task_complete(self, fn_or_task_name=None):
        if fn_or_task_name is None:
            return self._agent.on_task_complete()
        return self._agent.on_task_complete(fn_or_task_name)

    def on_action(self, fn_or_action_key=None):
        if fn_or_action_key is None:
            return self._agent.on_action()
        return self._agent.on_action(fn_or_action_key)

    def on_search_query(self, field_key: str):
        return self._agent.on_search_query(field_key)
