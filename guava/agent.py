from __future__ import annotations
from contextlib import contextmanager
from copy import copy
from datetime import timedelta
import inspect
import logging
import threading
import time
import warnings
import httpx

from typing import TYPE_CHECKING, Callable, Iterator, overload, Optional, Any, ParamSpec, cast, Literal
from websockets.sync.client import connect as ws_connect

if TYPE_CHECKING:
    from guava.testing.session import TestSession
from .telemetry import telemetry_client
from guava.types.call_info import CallInfo
from guava.types.incoming_call_action import IncomingCallAction, AcceptCall, DeclineCall
from guava import Client
from guava.utils import check_exactly_one
from urllib.parse import urlencode
from guava.socket.client import GuavaSocket, GuavaSocketClosedError
from . import listen_inbound
from guava.call import Call
from .utils import check_response, is_jsonable
from guava import campaigns, guavadialer_events
from pydantic import BaseModel
from functools import partial
from guava.types.call_info import PSTNCallInfo
from .webrtc_helper import run_webrtc_helper

from .events import (
    Event,
    CallerSpeechEvent,
    AgentSpeechEvent,
    TaskCompletedEvent,
    ActionItemCompletedEvent,
    AgentQuestionEvent,
    ActionRequestEvent,
    ChoiceQueryEvent,
    ExecuteActionEvent,
    ErrorEvent,
    WarningEvent,
    BotSessionEnded,
    OutboundCallFailed,
    OutboundCallConnected,
    EscalateEvent,
    DTMFPressedEvent,
    decode_event_dict,
)
from .commands import (
    Command,
    RegisteredHooksCommand,
    AnswerQuestionCommand,
    ChoiceResultCommand,
    ActionSuggestionCommand,
    ActionCandidate,
    ExpertErrorCommand
)
from guava.call_controller import CommandQueueEnd
from guava.edge_wake import run_wakeword_loop, run_wake_loop, run_button_loop
from .utils import preview
from .health import HealthContext, get_health_server

logger = logging.getLogger("guava.agent")


def edge_only(fn):
    import os
    from functools import wraps
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not os.environ.get("GUAVA_EDGE"):
            raise RuntimeError(
                f"{fn.__name__}() feature is only available when running with --edge "
                f"(e.g. `guava run --edge`). This feature is currently unavailable for public use " # TODO: remove
            )
        return fn(*args, **kwargs)
    return wrapper


def _accepts_positional_arg(fn: Callable, position: int) -> bool:
    """True if fn can accept a positional arg at the given (0-based) position."""
    try:
        params = inspect.signature(fn).parameters.values()
    except (TypeError, ValueError):
        return False
    positional = 0
    for p in params:
        if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD):
            positional += 1
        elif p.kind == p.VAR_POSITIONAL:
            return True
    return positional > position


class _TUILogHandler(logging.Handler):
    """Captures log records and feeds them into the chat TUI as 'system' messages."""
    def __init__(self, messages: list, lock: threading.Lock):
        super().__init__()
        self._messages = messages
        self._lock = lock
        self.setFormatter(logging.Formatter(
            "[%(levelname)s] (%(name)s) %(filename)s:%(lineno)d - %(message)s"
        ))

    def emit(self, record: logging.LogRecord) -> None:
        try:
            with self._lock:
                self._messages.append(("system", self.format(record), record.levelname))
        except Exception:
            self.handleError(record)

class SuggestedAction(BaseModel):
    key: str
    description: str | None = None

@telemetry_client.track_class()
class Agent:
    def __init__(self, name: Optional[str] = None, organization: Optional[str] = None, purpose: Optional[str] = None, voice: Optional[str] = None, accept_dtmf=True):
        self._name: Optional[str] = name
        self._organization: Optional[str] = organization
        self._purpose: Optional[str] = purpose
        self._voice: Optional[str] = voice
        self._accept_dtmf_for_numbers = accept_dtmf

        self._client = Client()

        self._on_call_received: Callable[[CallInfo], IncomingCallAction] = self.default_on_call_received
        self._on_call_start: Optional[Callable[[Call], None]] = None

        self._on_caller_speech: Optional[Callable[[Call, CallerSpeechEvent], None]] = None
        self._on_agent_speech: Optional[Callable[[Call, AgentSpeechEvent], None]] = None

        self._on_task_complete_generic: Optional[Callable[[Call, str], None]] = None
        self._on_task_complete_handlers: dict[str, Callable[[Call], None]] = {}

        self._on_validate_handlers: dict[str, Callable[[Call, Any],  Literal[True] | tuple[Literal[False], str]]] = {}

        self._on_question: Optional[Callable[[Call, str], str]] = None
        self._search_query_handlers: dict[str, Callable[[Call, str], tuple]] = {}

        self._on_action_requested: Optional[Callable[[Call, str], SuggestedAction | list[SuggestedAction] | None]] = None

        self._on_action_generic: Optional[Callable[[Call, str], None]] = None
        self._on_action_handlers: dict[str, Callable[[Call], None]] = {}

        self._on_session_end: Optional[Callable[[Call, BotSessionEnded], None] | Callable[[Call], None]] = None
        self._on_outbound_failed: Optional[Callable[[OutboundCallFailed], None]] = None

        self._on_escalate: Optional[Callable[[Call], None]] = None
        self._on_dtmf: Optional[Callable[[Call, DTMFPressedEvent], None]] = None

        self._edge_callbacks: dict[str, Callable[[Call], None]] = {}  # "press_enter" | "wakeword" | "wake"
        self._edge_wake_trigger: Optional[Callable[[], None]] = None
        self._wakeword_interpreter: Any = None
        self._edge_trigger: Optional[str] = None
        self._edge_trigger_lock = threading.Lock()
        self._edge_idle = threading.Event()
        self._edge_idle.set()

    @overload
    def on_call_received(self, fn: Callable[[CallInfo], IncomingCallAction], /) -> Callable[[CallInfo], IncomingCallAction]: ...
    @overload
    def on_call_received(self) -> Callable[[Callable[[CallInfo], IncomingCallAction]], Callable[[CallInfo], IncomingCallAction]]: ...

    def _register(self, attr: str, fn):
        """Shared logic for un-keyed decorators."""
        if fn is not None and callable(fn):
            # This handles the bare decorator case.
            setattr(self, attr, fn)
            return fn
        
        def decorator(fn):
            # This handles the decorator with parens case.
            setattr(self, attr, fn)
            return fn
        
        return decorator

    def on_call_received(self, fn=None):
        return self._register("_on_call_received", fn)

    def default_on_call_received(self, call_info: CallInfo) -> IncomingCallAction:
        return AcceptCall()

    @overload
    def on_call_start(self, fn: Callable[[Call], None], /) -> Callable[[Call], None]: ...
    @overload
    def on_call_start(self) -> Callable[[Callable[[Call], None]], Callable[[Call], None]]: ...

    def on_call_start(self, fn=None):
        return self._register("_on_call_start", fn)

    @overload
    def on_caller_speech(self, fn: Callable[[Call, CallerSpeechEvent], None], /) -> Callable[[Call, CallerSpeechEvent], None]: ...
    @overload
    def on_caller_speech(self) -> Callable[[Callable[[Call, CallerSpeechEvent], None]], Callable[[Call, CallerSpeechEvent], None]]: ...

    def on_caller_speech(self, fn=None):
        return self._register("_on_caller_speech", fn)

    @overload
    def on_agent_speech(self, fn: Callable[[Call, AgentSpeechEvent], None], /) -> Callable[[Call, AgentSpeechEvent], None]: ...
    @overload
    def on_agent_speech(self) -> Callable[[Callable[[Call, AgentSpeechEvent], None]], Callable[[Call, AgentSpeechEvent], None]]: ...

    def on_agent_speech(self, fn=None):
        return self._register("_on_agent_speech", fn)

    @overload
    def on_task_complete(self, fn: Callable[[Call, str], None], /) -> Callable[[Call, str], None]: ...
    @overload
    def on_task_complete(self) -> Callable[[Callable[[Call, str], None]], Callable[[Call, str], None]]: ...
    @overload
    def on_task_complete(self, task_name: str, /) -> Callable[[Callable[[Call], None]], Callable[[Call], None]]: ...

    @overload
    def on_question(self, fn: Callable[[Call, str], str], /) -> Callable[[Call, str], str]: ...
    @overload
    def on_question(self) -> Callable[[Callable[[Call, str], str]], Callable[[Call, str], str]]: ...

    def on_question(self, fn=None):
        return self._register("_on_question", fn)

    @overload
    def on_action_request(self, fn: Callable[[Call, str], SuggestedAction | list[SuggestedAction] | None], /) -> Callable[[Call, str], SuggestedAction | list[SuggestedAction] | None]: ...
    @overload
    def on_action_request(self) -> Callable[[Callable[[Call, str], SuggestedAction | list[SuggestedAction] | None]], Callable[[Call, str], SuggestedAction | list[SuggestedAction] | None]]: ...

    def on_action_request(self, fn=None):
        return self._register("_on_action_requested", fn)

    @overload
    def on_session_end(self, fn: Callable[[Call, BotSessionEnded], None], /) -> Callable[[Call, BotSessionEnded], None]: ...
    @overload
    def on_session_end(self, fn: Callable[[Call], None], /) -> Callable[[Call], None]: ...
    @overload
    def on_session_end(self) -> Callable[[Callable[[Call, BotSessionEnded], None]], Callable[[Call, BotSessionEnded], None]]: ... # Intentionally set to only two-arg.

    def on_session_end(self, fn=None):
        """
        Register a handler to be invoked when the session ends.
        The handler receives a Call object and a ``BotSessionEnded`` event.
        """
        return self._register("_on_session_end", fn)

    @overload
    def on_outbound_failed(self, fn: Callable[[OutboundCallFailed], None], /) -> Callable[[OutboundCallFailed], None]: ...
    @overload
    def on_outbound_failed(self) -> Callable[[Callable[[OutboundCallFailed], None]], Callable[[OutboundCallFailed], None]]: ...

    def on_outbound_failed(self, fn=None):
        return self._register("_on_outbound_failed", fn)

    def on_search_query(self, field_key: str) -> Callable[[Callable[[Call, str], tuple]], Callable[[Call, str], tuple]]:
        def decorator(fn: Callable[[Call, str], tuple]):
            self._search_query_handlers[field_key] = fn
            return fn
        return decorator

    @overload
    def on_reach_person(self, fn: Callable[[Call, str], None], /) -> Callable[[Call, str], None]: ...
    @overload
    def on_reach_person(self) -> Callable[[Callable[[Call, str], None]], Callable[[Call, str], None]]: ...

    def on_reach_person(self, fn=None):
        def register(fn):
            def handler(call: Call):
                fn(call, call.get_field("contact_availability"))
            self.on_task_complete("reach_person")(handler)
            return fn

        if fn is not None and callable(fn):
            return register(fn)
        return register

    def on_task_complete(self, fn_or_task_name=None):
        _mix_err = "Cannot mix a generic on_task_complete handler with per-task handlers."
        if fn_or_task_name is None:
            # @agent.on_task_complete()
            if self._on_task_complete_handlers:
                raise TypeError(_mix_err)
            def decorator(fn):
                self._on_task_complete_generic = fn
                return fn
            return decorator
        elif callable(fn_or_task_name):
            # @agent.on_task_complete (bare)
            if self._on_task_complete_handlers:
                raise TypeError(_mix_err)
            self._on_task_complete_generic = fn_or_task_name
            return fn_or_task_name
        else:
            # @agent.on_task_complete("task_name")
            task_name = fn_or_task_name
            if self._on_task_complete_generic is not None:
                raise TypeError(_mix_err)
            def decorator(fn):
                self._on_task_complete_handlers[task_name] = fn
                return fn
            return decorator
        
    def on_validate(self, field_key: str):
        def decorator(fn):
            self._on_validate_handlers[field_key] = fn
            return fn
        return decorator

    @overload
    def on_action(self, fn: Callable[[Call, str], None], /) -> Callable[[Call, str], None]: ...
    @overload
    def on_action(self) -> Callable[[Callable[[Call, str], None]], Callable[[Call, str], None]]: ...
    @overload
    def on_action(self, action_key: str, /) -> Callable[[Callable[[Call], None]], Callable[[Call], None]]: ...

    def on_action(self, fn_or_action_key=None):
        _mix_err = "Cannot mix a generic on_action handler with per-action handlers."
        if fn_or_action_key is None:
            # @agent.on_action()
            if self._on_action_handlers:
                raise TypeError(_mix_err)
            def decorator(fn):
                self._on_action_generic = fn
                return fn
            return decorator
        elif callable(fn_or_action_key):
            # @agent.on_action (bare)
            if self._on_action_handlers:
                raise TypeError(_mix_err)
            self._on_action_generic = fn_or_action_key
            return fn_or_action_key
        else:
            # @agent.on_action("action_key")
            action_key = fn_or_action_key
            if self._on_action_generic is not None:
                raise TypeError(_mix_err)
            def decorator(fn):
                self._on_action_handlers[action_key] = fn
                return fn
            return decorator
        
    @overload
    def on_escalate(self, fn: Callable[[Call], None], /) -> Callable[[Call], None]: ...
    @overload
    def on_escalate(self) -> Callable[[Callable[[Call], None]], Callable[[Call], None]]: ...

    def on_escalate(self, fn=None):
        return self._register("_on_escalate", fn)

    @overload
    def on_dtmf(self, fn: Callable[[Call, DTMFPressedEvent], None], /) -> Callable[[Call, DTMFPressedEvent], None]: ...
    @overload
    def on_dtmf(self) -> Callable[[Callable[[Call, DTMFPressedEvent], None]], Callable[[Call, DTMFPressedEvent], None]]: ...

    def on_dtmf(self, fn=None):
        return self._register("_on_dtmf", fn)

    @edge_only
    def on_press_enter(self, fn=None):
        def register(fn):
            self._edge_callbacks["press_enter"] = fn
            return fn
        if fn is not None and callable(fn):
            return register(fn)
        return register

    @edge_only
    def on_wakeword(self, fn=None, *, model: Optional[str] = None):
        from pathlib import Path
        from nanowakeword import NanoInterpreter  # type: ignore[import-not-found]

        model_dir = Path(__file__).parent / "models" / "heyguava"
        model_path = model or str(model_dir / "heyguava.onnx")

        self._wakeword_interpreter = NanoInterpreter.load_model(
            model_path,
            cascade=True,
            gate_threshold=0.3,
            vad_threshold=0.5,
        )

        def register(fn):
            self._edge_callbacks["wakeword"] = fn
            return fn
        if fn is not None and callable(fn):
            return register(fn)
        return register

    @edge_only
    def on_wake(self, *, trigger: Callable[[], None]):
        def decorator(fn: Callable[[Call], None]):
            self._edge_callbacks["wake"] = fn
            self._edge_wake_trigger = trigger
            return fn
        return decorator

    _P = ParamSpec("_P")

    def _invoke_handler(self, call: Call, name: str, inform_agent: bool, handler: Callable[_P, None], *args: _P.args, **kwargs: _P.kwargs) -> None:
        """Wraps invocation of a callback and logs an error. Use specifically for callbacks where the result is not used."""
        try:
            handler(*args, **kwargs)
        except Exception:
            logger.exception("An error occurred in the %s handler.", name)

            if inform_agent:
                call.send_command(ExpertErrorCommand(message=f"The expert encountered an error while processing {name}"))

    def _dispatch_event(self, call: Call, event: Event, test_session: Optional[TestSession] = None) -> None:
        match event:
            case CallerSpeechEvent():
                if self._on_caller_speech:
                    self._invoke_handler(call, "on_caller_speech", False, self._on_caller_speech, call, event)
            case AgentSpeechEvent():
                if self._on_agent_speech:
                    self._invoke_handler(call, "on_agent_speech", False, self._on_agent_speech, call, event)
            case TaskCompletedEvent():
                # Validate any fields that had validators attached
                errors = []
                for field_key in call._field_keys_by_task_id.get(event.task_id, []):
                    if field_key in self._on_validate_handlers:
                        result = self._on_validate_handlers[field_key](call, call.get_field(field_key))
                        if result is not True:
                            _, error = result
                            errors.append(error)

                if errors:
                    call.retry_task(reason=" ".join(errors))
                else:
                    logger.info("Task %s completed.", event.task_id)
                    try:
                        if self._on_task_complete_generic is not None:
                            self._on_task_complete_generic(call, event.task_id)
                        elif event.task_id in self._on_task_complete_handlers:
                            self._on_task_complete_handlers[event.task_id](call)
                        else:
                            logger.warning("No handler registered for completion of task '%s'", event.task_id)
                    except Exception:
                        # Log an error for the developer, but send a message back so the Agent knows the Expert encountered an error.
                        logger.exception("An error occurred in the on_task_complete('%s') handler.", event.task_id)
                        call.send_command(ExpertErrorCommand(message=f"The expert encountered an error while processing on_task_complete('{event.task_id}') - the task has failed."))
            case AgentQuestionEvent():
                logger.info("Received a question from agent: %s", event.question)
                if self._on_question is not None:
                    try:
                        answer = self._on_question(call, event.question)
                        call.send_command(AnswerQuestionCommand(question_id=event.question_id, answer=answer))
                    except Exception:
                        # Log the exception and inform the agent there was an error processing the question.
                        logger.exception("An error occurred in the on_question handler.")
                        call.send_command(AnswerQuestionCommand(question_id=event.question_id, answer="An error occurred and the question could not be answered."))
                else:
                    logger.warning("Received question but no on_question handler is registered: %s", event.question)
                    call.send_command(AnswerQuestionCommand(question_id=event.question_id, answer="I don't have an answer to that question."))
            case ActionRequestEvent():
                logger.info("Received action request %s: %s", event.intent_id, event.intent_summary)
                
                try:
                    suggestion = self._on_action_requested(call, event.intent_summary) if self._on_action_requested else None
                except Exception:
                    # Log the error and inform the agent.
                    logger.exception("An error occurred in the on_action_request handler.")
                    call.send_command(ExpertErrorCommand(message="The expert encountered an error while processing the on_action_request handler."))
                    suggestion = None

                if suggestion is None:
                    actions: list[ActionCandidate] = []
                elif isinstance(suggestion, SuggestedAction):
                    actions = [ActionCandidate(key=suggestion.key, description=suggestion.description or "")]
                else:
                    actions = [ActionCandidate(key=s.key, description=s.description or "") for s in suggestion]
                
                call.send_command(ActionSuggestionCommand(intent_id=event.intent_id, actions=actions))
            case ActionItemCompletedEvent():
                call._field_values[event.key] = event.payload
                if event.key and event.payload:
                    logger.info("Field %s updated.", event.key)
            case ExecuteActionEvent():
                logger.info("Executing action '%s'", event.action_key)

                # Track this for test sessions.
                if test_session:
                    test_session.executed_actions.append(event.action_key)

                # We may either be calling the generic action handler, or the action-keyed handler.
                on_action_func = None
                if self._on_action_generic is not None:
                    on_action_func = partial(self._on_action_generic, call, event.action_key)
                elif event.action_key in self._on_action_handlers:
                    on_action_func = partial(self._on_action_handlers[event.action_key], call)

                if on_action_func:
                    try:
                        response = on_action_func()
                        if response:
                            logger.info("Action execution request (%s) responded with: %s", event.action_key, response)
                            call.send_instruction(f"Responding to action execution {event.action_key}: {response}")
                    except Exception:
                        logger.exception("An error occurred in the on_action('%s') handler.", event.action_key)
                        call.send_command(ExpertErrorCommand(message=f"The expert encountered an error while processing the on_action('{event.action_key}') handler."))
                else:
                    logger.warning("No handler registered for action '%s'", event.action_key)
            case BotSessionEnded():
                logger.info("Session ended: %s", event.termination_reason)

                # Save the session result to the test session.
                if test_session:
                    test_session.termination_reason = event.termination_reason

                if self._on_session_end is not None:
                    # Pass event if accepted; single-arg form is deprecated.
                    if _accepts_positional_arg(self._on_session_end, 1):
                        self._invoke_handler(call, "on_session_end", False, cast(Callable[[Call, BotSessionEnded], None], self._on_session_end), call, event)
                    else:
                        warnings.warn(
                            "on_session_end handler should accept (Call, BotSessionEnded); "
                            "the single-argument form is deprecated and will be removed in a future version.",
                            DeprecationWarning,
                            stacklevel=2,
                        )
                        self._invoke_handler(call, "on_session_end", False, cast(Callable[[Call], None], self._on_session_end), call)
            case OutboundCallFailed():
                logger.error("Outbound call failed: %s", event.error_reason)
                if self._on_outbound_failed is not None:
                    self._invoke_handler(call, "on_outbound_failed", False, self._on_outbound_failed, event)
            case ErrorEvent():
                logger.error("Received error from Guava server: %s", event.content)
            case WarningEvent():
                logger.warning("Received warning from Guava server: %s", event.content)
            case OutboundCallConnected():
                # No handler for this yet.
                pass
            case ChoiceQueryEvent():
                logger.info("Received search query for field '%s': %s", event.field_key, event.query)
                handler = self._search_query_handlers.get(event.field_key)

                if handler is None:
                    logger.warning("Search query arrived for field '%s' with no handler attached.", event.field_key)
                    call.send_command(ExpertErrorCommand(message=f"The expert failed to handle on_search_query('{event.field_key}'). No results will be forthcoming."))
                else:
                    try:
                        choices, other_choices = handler(call, event.query)
                        call.send_command(ChoiceResultCommand(
                            field_key=event.field_key,
                            query_id=event.query_id,
                            matched_choices=choices,
                            other_choices=other_choices,
                        ))
                    except Exception:
                        # Send back an empty result and inform the agent of the failure.
                        logger.exception("An error occurred in the on_search_query('%s') handler.", event.field_key)
                        call.send_command(ExpertErrorCommand(message=f"The expert encountered an error while processing the on_search_query('{event.field_key}') handler. No results will be forthcoming."))
            case DTMFPressedEvent():
                if self._on_dtmf is not None:
                    self._invoke_handler(call, "on_dtmf", False, self._on_dtmf, call, event)
            case EscalateEvent():
                if self._on_escalate is not None:
                    # Inform the agent on escalation error.
                    self._invoke_handler(call, "on_escalate", True, self._on_escalate, call)
                elif event.requested_by == 'agent':
                    call.send_instruction("No escalation target set. Apologize for not being able to help, ask them to try calling another time, and hang up the call immediately.")
                elif event.requested_by == 'human':
                    call.send_instruction("Let them know there are no respresentatives available to take their call. Ask them if they would prefer to continue or to call another time.")                
            case _:
                logger.warning("Received unexpected event: %r", event)

    def _init_call(self, call_id: str, call_info: CallInfo, initial_variables: dict = {}) -> Call:
        call = Call(call_id, call_info)
        call.set_persona(
            agent_name=self._name,
            agent_purpose=self._purpose,
            organization_name=self._organization,
            voice=self._voice
        )
        call.send_command(
            RegisteredHooksCommand(
                has_on_question=self._on_question is not None,
                has_on_intent=False,
                has_on_action_requested=self._on_action_requested is not None,
                has_on_escalate=self._on_escalate is not None,
                accept_dtmf_for_numbers=self._accept_dtmf_for_numbers
            )
        )

        for key, value in initial_variables.items():
            call.set_variable(key, value)

        trigger = self._edge_trigger
        self._edge_trigger = None

        edge_cb = self._edge_callbacks.get(trigger) if trigger else None
        if edge_cb is not None:
            edge_cb(call)
        elif self._on_call_start is not None:
            self._on_call_start(call)

        return call

    def _attach_to_call(self, call_id: str, call_info: CallInfo, initial_variables: dict = {}, route="v2/connect-call", test_session: Optional[TestSession] = None):
        """Attach a call controller to a given call ID."""
        is_edge = self._edge_trigger is not None
        if is_edge:
            self._edge_idle.clear()
        try:
            command_thread = None

            call = self._init_call(call_id, call_info, initial_variables)

            with GuavaSocket[Command, Event | None](
                    f"call-connection-{call_id}",
                    self._client.get_websocket_url(f"{route}/{call_id}"),
                    client=self._client,
                    serializer=lambda command: command.model_dump(),
                    deserializer=lambda e: decode_event_dict(e),
                    max_age_seconds=18000 # Conservatively kill the connection after 5 hours.
                ) as gs:
                
                def drain_commands():
                    while gs.is_open():
                        command: Command | CommandQueueEnd = call._command_queue.get(block=True)
                        if isinstance(command, CommandQueueEnd):
                            break
                        
                        logger.debug("Sending command: %r for call ID: %s", command, call_id)
                        gs.send(command)
                        
                # On a background thread, drain commands to the websocket.
                command_thread = threading.Thread(target=drain_commands, daemon=True)
                command_thread.start()

                # Receive and dispatch events on the main thread.
                while gs.is_open():
                    event = gs.recv()

                    if event is None:
                        continue

                    self._dispatch_event(call, event, test_session=test_session)

                    if isinstance(event, (BotSessionEnded, OutboundCallFailed)):
                        break
        finally:
            call._shutdown_queue()
            if command_thread:
                command_thread.join()
            if is_edge:
                self._edge_idle.set()
    
    def listen_phone(self, agent_number: str) -> None:
        health_ctx = HealthContext()
        with get_health_server(health_ctx):
            self._listen_inbound(health_ctx, agent_number=agent_number)

    def listen_webrtc(self, webrtc_code: str | None = None) -> None:
        if not webrtc_code:
            logger.info("No WebRTC code provided. Creating a temporary one.")
            webrtc_code = self._client.create_webrtc_agent(ttl=timedelta(hours=1))

        health_ctx = HealthContext()
        with get_health_server(health_ctx):
            self._listen_inbound(health_ctx, webrtc_code=webrtc_code)

    def listen_sip(self, sip_code: str) -> None:
        health_ctx = HealthContext()
        with get_health_server(health_ctx):
            self._listen_inbound(health_ctx, sip_code=sip_code)

    def call_local(self, variables: dict[str, Any] = {}) -> None:
        webrtc_code = self._client.create_webrtc_agent(ttl=timedelta(minutes=5))
        threading.Thread(target=self._listen_inbound, kwargs={
            "health_ctx": HealthContext(), # No health-server for call_local.
            "webrtc_code": webrtc_code,
            "initial_variables": variables,
        }, daemon=True).start()
        run_webrtc_helper(webrtc_code, self._client._base_url)

    @edge_only
    def listen_for_wake(self, variables: dict[str, Any] = {}) -> None:
        """Persistent local mode. Starts the inbound listener, then loops
        waiting for button-press (Enter key) or wakeword triggers to start
        successive calls.

        Wakeword detection runs in-process via nanowakeword. Button press
        is handled via stdin. Both can be active simultaneously.

        The on_press_enter/on_wakeword/on_wake callbacks receive a Call object
        (like on_call_start) once the triggered call connects."""

        has_button = "press_enter" in self._edge_callbacks
        has_wakeword = "wakeword" in self._edge_callbacks
        has_wake = self._edge_wake_trigger is not None

        if not has_button and not has_wakeword and not has_wake:
            logger.warning("listen_for_wake() called but no trigger is registered (on_press_enter, on_wakeword, or on_wake).")
            return

        def _listen_inbound_safe():
            while True:
                try:
                    webrtc_code = self._client.create_webrtc_agent(ttl=timedelta(hours=24))
                    logger.info("Listener connected (code=%s…)", webrtc_code[:8])
                    self._listen_inbound(HealthContext(), webrtc_code=webrtc_code, initial_variables=variables)
                    logger.info("Listener disconnected, renewing code…")
                except Exception:
                    logger.exception("Listener crashed, reconnecting in 5 s…")
                    time.sleep(5)

        threading.Thread(target=_listen_inbound_safe, daemon=True).start()

        trigger_url = self._client.get_http_url("api/trigger-local-call")

        if has_wakeword:
            threading.Thread(target=run_wakeword_loop, args=(self, trigger_url), daemon=True).start()
            logger.info("Wakeword detection active (nanowakeword).")

        if has_wake:
            assert self._edge_wake_trigger is not None
            threading.Thread(target=run_wake_loop, args=(self, trigger_url, self._edge_wake_trigger), daemon=True).start()
            logger.info("Custom wake trigger active.")

        if has_button:
            run_button_loop(self, trigger_url, has_wakeword=has_wakeword)
        else:
            logger.info("Listening locally (no Enter key trigger).")
            threading.Event().wait()

    def _listen_inbound(self, health_ctx: HealthContext, agent_number: str | None = None, webrtc_code: str | None = None, sip_code: str | None = None, initial_variables: dict[str, Any] = {}):
        if not check_exactly_one(agent_number, webrtc_code, sip_code):
            raise TypeError("One of agent_number, webrtc_code, or sip_code must be provided.")
        

        query = {}
        if agent_number:
            query["phone_number"] = agent_number
        elif webrtc_code:
            query["webrtc_code"] = webrtc_code
        elif sip_code:
            query["sip_code"] = sip_code
        query_string = urlencode(query)

        try:
            with GuavaSocket[listen_inbound.ClientMessage, listen_inbound.ServerMessage](
                    "listen-inbound",
                    self._client.get_websocket_url(f"v2/listen-inbound?{query_string}"),
                    client=self._client,
                    serializer=lambda msg: msg.model_dump(),
                    deserializer=listen_inbound.decode_server_message,
                ) as gs:
                
                # Start listening and get the response.
                while gs.is_open():
                    server_message = gs.recv()
                    match server_message:
                        case listen_inbound.ListenStarted():
                            health_ctx.ready()
                            if agent_number:
                                logger.info("Started listing on phone number %s. %d other listeners registered.", agent_number, server_message.other_listeners)
                            elif webrtc_code:
                                logger.info("Started listing on WebRTC code %s. %d other listeners registered.", webrtc_code, server_message.other_listeners)
                                logger.info("WebRTC URL: %s?webrtc_code=%s", self._client.get_http_url('debug-webrtc'), webrtc_code)
                            elif sip_code:
                                logger.info("Started listening on SIP code %s. %d other listeners registered.", sip_code, server_message.other_listeners)
                        case listen_inbound.IncomingCall():
                            gs.send(listen_inbound.ClaimCall(call_id=server_message.call_id))
                        case listen_inbound.AssignCall():
                            logger.info("Received call (session ID: %s), info: %r", server_message.call_id, server_message.call_info)
                            try:
                                call_action = self._on_call_received(server_message.call_info)
                                if isinstance(call_action, DeclineCall):
                                    logger.info("Declining call...")
                                    gs.send(listen_inbound.DeclineCall(call_id=server_message.call_id))
                                elif isinstance(call_action, AcceptCall):
                                    logger.info("Accepting call...")
                                    gs.send(listen_inbound.AnswerCall(call_id=server_message.call_id))

                                    threading.Thread(target=self._attach_to_call, args=(server_message.call_id, server_message.call_info, initial_variables), daemon=True).start()
                                else:
                                    logger.error("Unknown action for incoming call: %r", call_action)
                            except Exception:
                                logger.exception("Failed to initialize call controller.")
        finally:
            health_ctx.stopped()

    def call_phone(self, from_number, to_number, variables: dict[str, Any] = {}) -> None:
        for key, val in variables.items():
            if not is_jsonable(val):
                raise ValueError(f"Variable '{key}' value is not JSON serializable: {val!r}")

        response = check_response(httpx.post(
            self._client.get_http_url("v2/create-outbound"),
            headers=self._client._get_headers(),
            params={
                "from_number": from_number,
                "to_number": to_number
            }
        ))
        call_id = response.json()["call_id"]
        logger.info("Outbound call created with session ID: %s", call_id)
        self._attach_to_call(call_id, PSTNCallInfo(from_number=from_number, to_number=to_number), variables)

    def _serve_campaign(
        self,
        health_ctx: HealthContext,
        campaign_code: str,
    ):
        campaign = campaigns.get_campaign_by_code(campaign_code)
        def initiate_call(call_id: str, contact_data: Any):
            # TODO: The server needs to send the from_number that it chose in the case of multiple.
            # outbound numbers attached to a campaign.
            call_info = PSTNCallInfo(from_number=None, to_number=contact_data.get('phone_number'))
            data = contact_data.get('data', {})

            gs.send(guavadialer_events.ControllerReady(call_id=call_id))
            self._attach_to_call(call_id, call_info, initial_variables=data, route="v2/connect-campaign-call")

        logger.info("Connecting to campaign '%s' (id: %s).", campaign.name, campaign.id)
        try:
            with GuavaSocket[guavadialer_events.ClientMessage, guavadialer_events.ServerMessage](
                    "serve-campaign",
                    self._client.get_websocket_url(f"v1/serve-campaign/{campaign.id}"),
                    client=self._client,
                    serializer=lambda msg: msg.model_dump(),
                    deserializer=guavadialer_events.decode_server_message,
                ) as gs:

                active_call_threads: list[threading.Thread] = []

                try:
                    while gs.is_open():
                        server_message = gs.recv()
                        match server_message:
                            case guavadialer_events.ListenStarted():
                                logger.info("Listening for calls on campaign '%s'. Ready.", campaign.name)
                                health_ctx.ready()
                            case guavadialer_events.InitiateAndAssignCall():
                                # Only used in controller mode. In headless mode the server handles calls directly.
                                log_phone = server_message.contact_data.get('phone_number') if server_message.contact_data else '?'
                                logger.info("Ready to make call, id %s — initiating call setup and dispatch for contact %s.", server_message.call_id, log_phone)
                                t = threading.Thread(
                                    target=initiate_call,
                                    args=(server_message.call_id, server_message.contact_data),
                                    daemon=True,
                                )
                                active_call_threads.append(t)
                                t.start()
                except KeyboardInterrupt:
                    alive = [t for t in active_call_threads if t.is_alive()]
                    if alive:
                        logger.info("Received Ctrl-C. Detaching from campaign - waiting for %d active calls to finish (Ctrl-C again to force exit).", len(alive))
                        for t in alive:
                            t.join()
                        logger.info("All active calls finished. Shutting down.")
        except GuavaSocketClosedError:
            logger.info("Campaign '%s' disconnected.", campaign.name)
        finally:
            health_ctx.stopped()

    def attach_campaign(
        self,
        campaign_code: str
    ) -> None:
        health_ctx = HealthContext()
        with get_health_server(health_ctx):
            self._serve_campaign(health_ctx, campaign_code)

    @preview("Agent Testing")
    def test_roleplay(self, roleplay_prompt: str, variables=None) -> "TestSession":
        """Deprecated: use agent.roleplay() instead."""
        warnings.warn(
            "test_roleplay() is deprecated; use roleplay() instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        return self.roleplay(roleplay_prompt, variables)

    @preview("Agent Testing")
    def roleplay(self, roleplay_prompt: str, variables=None) -> "TestSession":
        """Run an automated test conversation where an LLM plays the caller.

        Args:
            roleplay_prompt: Instructions for the simulated caller, e.g. "You are
                a frustrated customer trying to cancel your subscription."
            variables: Optional dict of initial call variables passed to the agent.

        Returns:
            The completed TestSession. Call ``session.evaluate()`` to assert
            pass/fail criteria, or ``session.get_transcript()`` to get the transcript.
        """
        from websockets.exceptions import ConnectionClosedOK
        from guava.helpers.llm import _generate
        from guava.testing.protocol import BotTTS
        from pydantic import BaseModel

        class _RoleplayAction(BaseModel):
            action: Literal["speak", "hangup"]
            utterance: str | None = None

        schema = _RoleplayAction.model_json_schema()

        with self.test(variables=variables) as session:
            try:
                events_before = len(session._events)
                while True:
                    session.wait_for_turn()

                    for event in session._events[events_before:]:
                        if isinstance(event, BotTTS):
                            logger.info("(Roleplay Session) [agent]: %s", event.transcript)
                    events_before = len(session._events)

                    transcript = session.get_transcript()

                    prompt = f"""{roleplay_prompt}

You are roleplaying as a caller on a phone call. Decide what to do next based on the conversation so far.

Conversation:
{transcript if transcript else "(The agent has not spoken yet)"}

Choose "speak" and provide your next utterance, or choose "hangup" if the conversation has naturally concluded."""

                    result = _generate(prompt, json_schema=schema)
                    action = _RoleplayAction.model_validate_json(result)

                    if action.action == "hangup":
                        logger.info("(Roleplay Session) [caller hangs up]")
                        break

                    if action.action == "speak" and action.utterance:
                        logger.info("(Roleplay Session) [caller]: %s", action.utterance)
                        session.say(action.utterance)
            except ConnectionClosedOK:
                logger.info("Roleplay session ended by server.")

            for event in session._events[events_before:]:
                if isinstance(event, BotTTS):
                    logger.info("(Roleplay Session) [agent]: %s", event.transcript)

        return session

    @preview("Agent Testing")
    def chat(self, variables=None) -> None:
        """Start an interactive terminal chat session with the agent.

        Launches a curses TUI with a scrolling conversation panel and an input
        line. Agent speech and SDK log output appear in real time without waiting
        for the user to finish typing. Press Ctrl+C or let the agent end the
        session to exit.

        Args:
            variables: Optional dict of initial call variables passed to the agent.
        """
        import curses
        import textwrap
        import threading
        from guava.testing.protocol import BotTTS

        # Shared message log: (speaker, text, log-levelname or None).
        # Written by both _reader (agent messages) and _TUILogHandler (log lines);
        # read by _render on every frame. Protected by _lock.
        _messages: list[tuple[str, str, str | None]] = []
        _lock = threading.Lock()
        _done = threading.Event()  # set when the session ends or the reader errors

        with self.test(variables=variables) as session:
            def _reader():
                # Background thread: pulls events from the test session WebSocket
                # and appends agent speech to _messages. Sets _done on any error
                # or connection close so the render loop can exit cleanly.
                try:
                    while not _done.is_set():
                        event = session.recv()
                        if isinstance(event, BotTTS):
                            with _lock:
                                _messages.append(("agent", event.transcript, None))
                except Exception:
                    _done.set()

            def _render(stdscr):
                # curses.wrapper calls this with a fully-initialized screen (stdscr).
                # Layout: rows 0..(height-3) = scrolling conversation; row height-2 =
                # separator; row height-1 = input prompt.

                curses.use_default_colors()  # lets -1 mean "terminal default background"
                curses.start_color()
                curses.init_pair(1, curses.COLOR_CYAN, -1)    # agent
                curses.init_pair(2, curses.COLOR_GREEN, -1)   # you
                curses.init_pair(3, curses.COLOR_YELLOW, -1)  # WARNING
                curses.init_pair(4, curses.COLOR_RED, -1)     # ERROR / CRITICAL

                curses.curs_set(1)
                # halfdelay(2): getch blocks for up to 200ms then returns -1.
                # This lets the render loop tick at ~5fps so agent messages appear
                # promptly without busy-spinning while the user is typing.
                curses.halfdelay(2)

                # Swap existing stream handlers for our TUI handler so log output
                # doesn't corrupt the curses display.
                root_logger = logging.getLogger()
                tui_handler = _TUILogHandler(_messages, _lock)
                original_handlers = root_logger.handlers[:]
                for h in original_handlers:
                    root_logger.removeHandler(h)
                root_logger.addHandler(tui_handler)

                reader_thread = threading.Thread(target=_reader, daemon=True)
                reader_thread.start()

                input_buf = ""  # characters typed by the user since last Enter

                try:
                    while True:
                        height, width = stdscr.getmaxyx()
                        conv_height = max(1, height - 2)  # rows available for conversation

                        stdscr.erase()  # clear the screen before redrawing each frame

                        with _lock:
                            msgs = list(_messages)

                        # Word-wrap every message into terminal-width lines, carrying
                        # the speaker and level through so the renderer can color them.
                        lines: list[tuple[str, str, str | None]] = []  # (line_text, speaker, level)
                        for speaker, text, level in msgs:
                            prefix = f"[{speaker}]: " if speaker != "system" else ""
                            wrapped = textwrap.wrap(
                                text,
                                width=max(1, width - 1),
                                initial_indent=prefix,
                                subsequent_indent=" " * len(prefix),
                            ) or [prefix]
                            for line in wrapped:
                                lines.append((line, speaker, level))

                        # Show only the last conv_height lines (auto-scroll to bottom).
                        visible = lines[max(0, len(lines) - conv_height):]
                        for i, (line, speaker, level) in enumerate(visible[:conv_height]):
                            if speaker == "agent":
                                attr = curses.color_pair(1)
                            elif speaker == "you":
                                attr = curses.color_pair(2)
                            elif level in ("ERROR", "CRITICAL"):
                                attr = curses.color_pair(4) | (curses.A_BOLD if level == "CRITICAL" else 0)
                            elif level == "WARNING":
                                attr = curses.color_pair(3)
                            else:  # DEBUG / INFO
                                attr = curses.A_DIM
                            try:
                                stdscr.addstr(i, 0, line[:width - 1], attr)
                            except curses.error:
                                pass

                        # Draw the separator and input line at the bottom.
                        prompt = "[you]: "
                        display = prompt + input_buf
                        try:
                            stdscr.addstr(height - 2, 0, "─" * (width - 1), curses.A_DIM)
                            stdscr.addstr(height - 1, 0, display[:width - 1], curses.color_pair(2))
                            stdscr.move(height - 1, min(len(display), width - 1))
                        except curses.error:
                            pass

                        stdscr.refresh()  # flush everything to the terminal at once

                        if _done.is_set():
                            try:
                                stdscr.addstr(height - 1, 0, "Session ended. Press any key to exit."[:width - 1])
                            except curses.error:
                                pass
                            stdscr.refresh()
                            while stdscr.getch() == -1:  # loop until a real key arrives
                                pass
                            return

                        ch = stdscr.getch()
                        if ch == -1:
                            continue  # halfdelay timeout — just re-render
                        elif ch in (curses.KEY_ENTER, 10, 13):
                            utterance = input_buf.strip()
                            if utterance:
                                with _lock:
                                    _messages.append(("you", utterance, None))
                                session.say(utterance)
                            input_buf = ""
                        elif ch in (curses.KEY_BACKSPACE, 127, 8):  # terminals send different codes
                            input_buf = input_buf[:-1]
                        elif ch == 3:  # Ctrl+C
                            return
                        elif 32 <= ch < 127:  # printable ASCII
                            input_buf += chr(ch)
                finally:
                    # Always restore the original log handlers, even if curses crashes.
                    root_logger.removeHandler(tui_handler)
                    for h in original_handlers:
                        root_logger.addHandler(h)

            try:
                curses.wrapper(_render)
            except KeyboardInterrupt:
                pass

    @preview("Agent Testing")
    def patch(self) -> "Agent":
        """Return a copy of this agent with independently overridable callbacks.

        Use this in tests to register alternative handlers on the copy without
        affecting the original agent.

        Returns:
            A new Agent instance.
        """
        cloned = copy(self)

        # Callback dictionaries need to be cloned one level deeper.
        cloned._on_task_complete_handlers = self._on_task_complete_handlers.copy()
        cloned._on_action_handlers = self._on_action_handlers.copy()
        cloned._search_query_handlers = self._search_query_handlers.copy()
        cloned._on_validate_handlers = self._on_validate_handlers.copy()
        cloned._edge_callbacks = self._edge_callbacks.copy()

        return cloned

    @preview("Agent Testing")
    @contextmanager
    def test(self, variables=None) -> Iterator[TestSession]:
        """Context manager that runs the agent against a live test session.

        Connects to the Guava test endpoint, starts the agent's call handling,
        and yields a TestSession for driving the conversation programmatically.

        Args:
            variables: Optional dict of initial call variables passed to the agent.

        Yields:
            A TestSession. Call ``session.say()`` to inject caller utterances,
            ``session.wait_for_turn()`` to block until the agent finishes speaking,
            ``session.evaluate()`` to assert pass/fail criteria, or
            ``session.get_transcript()`` to get the transcript.
        """
        from guava.testing.protocol import SessionStarted
        from guava.testing.session import TestSession

        call_thread = None
        try:
            with ws_connect(
                self._client.get_websocket_url("v1/test-agent"),
                additional_headers=self._client._get_headers(),
                open_timeout=10,
                close_timeout=10,
            ) as ws:
                session_started = SessionStarted.model_validate_json(ws.recv())

                test_session = TestSession(ws)
                call_thread = threading.Thread(
                    target=self._attach_to_call,
                    args=(session_started.session_id, PSTNCallInfo(from_number=None, to_number="+15555555555")),
                    kwargs={"initial_variables": variables or {}, "test_session": test_session},
                    daemon=True,
                )
                call_thread.start()

                yield test_session
        finally:
            if call_thread:
                call_thread.join()
