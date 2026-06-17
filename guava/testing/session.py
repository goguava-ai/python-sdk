import logging
import secrets

from websockets.sync.connection import Connection
from websockets.exceptions import ConnectionClosedOK
from pydantic import BaseModel, TypeAdapter
from guava.testing.protocol import (
    BotTTS,
    InjectASR,
    Ping,
    Pong,
    TestingCommand,
    TestingEvent,
    TurnStarted,
    WaitForTurn,
)
from typing import List


class _CriterionResult(BaseModel):
    passed: bool
    reasoning: str | None = None


class _EvalResponse(BaseModel):
    results: list[_CriterionResult]


_event_adapter = TypeAdapter(TestingEvent)

logger = logging.getLogger("guava.testing.session")


class TestSession:
    def __init__(self, ws: Connection):
        self._ws = ws
        self._events = []
        self.executed_actions: List[str] = []
        self.termination_reason: str | None = None

    def _send(self, command: TestingCommand):
        self._ws.send(command.model_dump_json())

    def say(self, utterance: str):
        message = InjectASR(utterance=utterance)
        self._events.append(message)
        self._send(message)

    def recv(self) -> TestingEvent:
        while True:
            try:
                message = self._ws.recv(timeout=5)
                event = _event_adapter.validate_json(message)
                match event:
                    case BotTTS():
                        self._events.append(event)
                        return event
                    case Ping():
                        self._send(Pong())
                    case _:
                        return event
            except TimeoutError:
                self._send(Ping())

    def get_transcript(self) -> str:
        lines = []
        for event in self._events:
            match event:
                case InjectASR():
                    lines.append(f"[caller]: {event.utterance}")
                case BotTTS():
                    lines.append(f"[agent]: {event.transcript}")
        return "\n".join(lines)

    def wait_for_turn(self):
        # Generate a request ID and send the command.
        request_id = secrets.token_hex(8)
        self._send(WaitForTurn(request_id=request_id))

        # Wait until we get a "TurnStarted" event for that request_id.
        while True:
            match self.recv():
                case TurnStarted() as e if e.request_id == request_id:
                    return

    def wait_for_end(self):
        try:
            while True:
                self.recv()
        except ConnectionClosedOK:
            logger.info("Testing session ended by server...")

    def evaluate(
        self,
        pass_criteria: list[str] | None = None,
        fail_criteria: list[str] | None = None,
    ) -> None:
        from guava.helpers.llm import _generate

        pass_criteria = pass_criteria or []
        fail_criteria = fail_criteria or []
        all_criteria = [("pass", c) for c in pass_criteria] + [("fail", c) for c in fail_criteria]

        if not all_criteria:
            return

        transcript = self.get_transcript()
        criteria_list = "\n".join(f"{i + 1}. {c}" for i, (_, c) in enumerate(all_criteria))

        prompt = f"""Evaluate whether the following criteria are met based on the conversation transcript below.
Return one result object per criterion in the same order as listed.

Transcript:
{transcript if transcript else "(empty — no conversation occurred)"}

Criteria:
{criteria_list}"""

        raw = _generate(prompt, json_schema=_EvalResponse.model_json_schema())
        response = _EvalResponse.model_validate_json(raw)

        if len(response.results) != len(all_criteria):
            raise AssertionError(
                f"Evaluation returned {len(response.results)} results for {len(all_criteria)} criteria."
            )

        failures = []
        for (kind, criterion), result in zip(all_criteria, response.results):
            if kind == "pass" and not result.passed:
                msg = f"Pass criterion not met: {criterion!r}"
                if result.reasoning:
                    msg += f" — {result.reasoning}"
                failures.append(msg)
            elif kind == "fail" and result.passed:
                msg = f"Fail criterion triggered: {criterion!r}"
                if result.reasoning:
                    msg += f" — {result.reasoning}"
                failures.append(msg)

        if failures:
            raise AssertionError(
                "Session evaluation failed:\n" + "\n".join(f"  • {f}" for f in failures)
            )
