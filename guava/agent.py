from datetime import timedelta
import logging
import threading
import httpx
import time

from typing import Callable, overload, Optional, Any
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
)
from guava.call_controller import CommandQueueEnd

logger = logging.getLogger("guava.agent")

class SuggestedAction(BaseModel):
    key: str
    description: str | None = None

@telemetry_client.track_class()
class Agent:
    def __init__(self, name: Optional[str] = None, organization: Optional[str] = None, purpose: Optional[str] = None, voice: Optional[str] = None):
        self._name: Optional[str] = name
        self._organization: Optional[str] = organization
        self._purpose: Optional[str] = purpose
        self._voice: Optional[str] = voice

        self._client = Client()

        self._on_call_received: Callable[[CallInfo], IncomingCallAction] = self.default_on_call_received
        self._on_call_start: Optional[Callable[[Call], None]] = None

        self._on_caller_speech: Optional[Callable[[Call, CallerSpeechEvent], None]] = None
        self._on_agent_speech: Optional[Callable[[Call, AgentSpeechEvent], None]] = None

        self._on_task_complete_generic: Optional[Callable[[Call, str], None]] = None
        self._on_task_complete_handlers: dict[str, Callable[[Call], None]] = {}

        self._on_question: Optional[Callable[[Call, str], str]] = None
        self._search_query_handlers: dict[str, Callable[[Call, str], tuple]] = {}

        self._on_action_requested: Optional[Callable[[Call, str], SuggestedAction | None]] = None

        self._on_action_generic: Optional[Callable[[Call, str], None]] = None
        self._on_action_handlers: dict[str, Callable[[Call], None]] = {}

        self._on_session_end: Optional[Callable[[Call], None]] = None
        self._on_outbound_failed: Optional[Callable[[OutboundCallFailed], None]] = None

        self._on_escalate: Optional[Callable[[Call], None]] = None
        self._on_dtmf: Optional[Callable[[Call, DTMFPressedEvent], None]] = None

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
    def on_task_complete(self, task_name: str) -> Callable[[Callable[[Call], None]], Callable[[Call], None]]: ...

    @overload
    def on_question(self, fn: Callable[[Call, str], str], /) -> Callable[[Call, str], str]: ...
    @overload
    def on_question(self) -> Callable[[Callable[[Call, str], str]], Callable[[Call, str], str]]: ...

    def on_question(self, fn=None):
        return self._register("_on_question", fn)

    @overload
    def on_action_request(self, fn: Callable[[Call, str], SuggestedAction | None], /) -> Callable[[Call, str], SuggestedAction | None]: ...
    @overload
    def on_action_request(self) -> Callable[[Callable[[Call, str], SuggestedAction | None]], Callable[[Call, str], SuggestedAction | None]]: ...

    def on_action_request(self, fn=None):
        return self._register("_on_action_requested", fn)

    @overload
    def on_session_end(self, fn: Callable[[Call], None], /) -> Callable[[Call], None]: ...
    @overload
    def on_session_end(self) -> Callable[[Callable[[Call], None]], Callable[[Call], None]]: ...

    def on_session_end(self, fn=None):
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

    @overload
    def on_action(self, fn: Callable[[Call, str], None], /) -> Callable[[Call, str], None]: ...
    @overload
    def on_action(self) -> Callable[[Callable[[Call, str], None]], Callable[[Call, str], None]]: ...
    @overload
    def on_action(self, action_key: str) -> Callable[[Callable[[Call], None]], Callable[[Call], None]]: ...

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

    def _dispatch_event(self, call: Call, event: Event) -> None:
        match event:
            case CallerSpeechEvent():
                if self._on_caller_speech:
                    self._on_caller_speech(call, event)
            case AgentSpeechEvent():
                if self._on_agent_speech:
                    self._on_agent_speech(call, event)
            case TaskCompletedEvent():
                logger.info("Task %s completed.", event.task_id)
                if self._on_task_complete_generic is not None:
                    self._on_task_complete_generic(call, event.task_id)
                elif event.task_id in self._on_task_complete_handlers:
                    self._on_task_complete_handlers[event.task_id](call)
                else:
                    logger.warning("No handler registered for completion of task '%s'", event.task_id)
            case AgentQuestionEvent():
                if self._on_question is not None:
                    try:
                        logger.info("Received question from bot: %s", event.question)
                        answer = self._on_question(call, event.question)
                        call.send_command(AnswerQuestionCommand(question_id=event.question_id, answer=answer))
                    except Exception:
                        logger.exception("Error occurred while answering question.")
                        call.send_command(AnswerQuestionCommand(question_id=event.question_id, answer="An error occurred and the question could not be answered."))
                else:
                    logger.warning("Received question but no on_question handler is registered: %s", event.question)
                    call.send_command(AnswerQuestionCommand(question_id=event.question_id, answer="I don't have an answer to that question."))
            case ActionRequestEvent():
                logger.info("Received action request %s: %s", event.intent_id, event.intent_summary)
                if self._on_action_requested is not None:
                    suggestion = self._on_action_requested(call, event.intent_summary)
                    if suggestion is not None:
                        call.send_command(ActionSuggestionCommand(
                            intent_id=event.intent_id,
                            action_key=suggestion.key,
                            action_description=suggestion.description or "",
                        ))
                    else:
                        call.send_command(ActionSuggestionCommand(intent_id=event.intent_id, action_key=None))
                else:
                    call.send_command(ActionSuggestionCommand(intent_id=event.intent_id, action_key=None))
            case ActionItemCompletedEvent():
                call._field_values[event.key] = event.payload
                if event.key and event.payload:
                    logger.info("Field %s updated with value: %r", event.key, event.payload)
            case ExecuteActionEvent():
                logger.info("Executing action '%s'", event.action_key)
                on_action_func = None
                if self._on_action_generic is not None:
                    on_action_func = partial(self._on_action_generic, call, event.action_key)
                elif event.action_key in self._on_action_handlers:
                    on_action_func = partial(self._on_action_handlers[event.action_key], call)
                if on_action_func:
                    response = on_action_func()
                    if response:
                        logger.info("Action execution request (%s) responded with: %s", event.action_key, response)
                        call.send_instruction(f"Responding to action execution {event.action_key}: {response}")
                else:
                    logger.warning("No handler registered for action '%s'", event.action_key)
            case BotSessionEnded():
                logger.info("Session ended: %s", event.termination_reason)
                if self._on_session_end is not None:
                    self._on_session_end(call)
            case OutboundCallFailed():
                logger.error("Outbound call failed: %s", event.error_reason)
                if self._on_outbound_failed is not None:
                    self._on_outbound_failed(event)
            case ErrorEvent():
                logger.error("Received error event: %s", event.content)
            case WarningEvent():
                logger.warning("Received warning event: %s", event.content)
            case OutboundCallConnected():
                # No handler for this yet.
                pass
            case ChoiceQueryEvent():
                logger.info("Received search query for field '%s': %s", event.field_key, event.query)
                handler = self._search_query_handlers.get(event.field_key)
                if handler is None:
                    logger.warning("Search query arrived for field '%s' with no handler attached.", event.field_key)
                else:
                    choices, other_choices = handler(call, event.query)
                    call.send_command(ChoiceResultCommand(
                        field_key=event.field_key,
                        query_id=event.query_id,
                        matched_choices=choices,
                        other_choices=other_choices,
                    ))
            case DTMFPressedEvent():
                if self._on_dtmf is not None:
                    self._on_dtmf(call, event)
            case EscalateEvent():
                if self._on_escalate is not None:
                    self._on_escalate(call)
                elif event.requested_by == 'agent':
                    call.send_instruction("No escalation target set. Apologize for not being able to help, ask them to try calling another time, and hang up the call immediately.")
                elif event.requested_by == 'human':
                    call.send_instruction("Let them know there are no respresentatives available to take their call. Ask them if they would prefer to continue or to call another time.")
            case _:
                logger.warning("Received unexpected event: %r", event)

    def _init_call(self, call_id: str, initial_variables: dict = {}) -> Call:
        call = Call(call_id)
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
            )
        )

        for key, value in initial_variables.items():
            call.set_variable(key, value)

        if self._on_call_start is not None:
            self._on_call_start(call)

        return call

    def _attach_to_call(self, call_id: str, initial_variables: dict = {}, route="v2/connect-call"):
        """Attach a call controller to a given call ID."""
        try:
            command_thread = None

            call = self._init_call(call_id, initial_variables)

            with GuavaSocket[Command, Event | None](
                    f"call-connection-{call_id}",
                    self._client.get_websocket_url(f"{route}/{call_id}"), 
                    headers=self._client._get_headers(),
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

                    self._dispatch_event(call, event)

                    if isinstance(event, (BotSessionEnded, OutboundCallFailed)):
                        break
        finally:
            call._shutdown_queue()
            if command_thread:
                command_thread.join()
    
    def listen_phone(self, agent_number: str) -> None:
        self._listen_inbound(agent_number=agent_number)

    def listen_webrtc(self, webrtc_code: str | None = None) -> None:
        if not webrtc_code:
            logger.info("No WebRTC code provided. Creating a temporary one.")
            webrtc_code = self._client.create_webrtc_agent(ttl=timedelta(hours=1))
        self._listen_inbound(webrtc_code=webrtc_code)

    def listen_sip(self, sip_code: str) -> None:
        self._listen_inbound(sip_code=sip_code)

    def call_local(self) -> None:
        import sys
        import importlib.util

        # First check that required deps are available.
        required_packages = ["aiortc", "sounddevice", "numpy"]
        needed_packages = [pkg for pkg in required_packages if importlib.util.find_spec(pkg) is None]

        if needed_packages:
            print("Local calling requires the following additional dependencies to be installed:", needed_packages)
            print("- To install using pip, run: pip install " + ' '.join(needed_packages))
            print("- To install using uv, run: uv add " + ' '.join(needed_packages))
            sys.exit(1)

        import asyncio
        from .terminal_call import TerminalCall
        webrtc_code = self._client.create_webrtc_agent(ttl=timedelta(minutes=5))

        threading.Thread(target=self._listen_inbound, kwargs={
            "webrtc_code": webrtc_code
        }, daemon=True).start()
        asyncio.run(TerminalCall(self._client, webrtc_code).start())

    def _listen_inbound(self, agent_number: str | None = None, webrtc_code: str | None = None, sip_code: str | None = None):
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
        with GuavaSocket[listen_inbound.ClientMessage, listen_inbound.ServerMessage](
                "listen-inbound",
                self._client.get_websocket_url(f"v2/listen-inbound?{query_string}"),
                headers=self._client._get_headers(),
                serializer=lambda msg: msg.model_dump(),
                deserializer=listen_inbound.decode_server_message,
            ) as gs:
            
            # Start listening and get the response.
            while gs.is_open():
                server_message = gs.recv()
                match server_message:
                    case listen_inbound.ListenStarted():
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

                                threading.Thread(target=self._attach_to_call, args=(server_message.call_id, ), daemon=True).start()
                            else:
                                logger.error("Unknown action for incoming call: %r", call_action)
                        except Exception:
                            logger.exception("Failed to initialize call controller.")

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
        self._attach_to_call(call_id, variables)

    def _serve_campaign(
        self,
        campaign: "campaigns.Campaign",
    ):
        def initiate_call(call_id: str, contact_data: Any):
            data = contact_data.get('data', {})
            gs.send(guavadialer_events.ControllerReady(call_id=call_id))
            self._attach_to_call(call_id, initial_variables=data, route="v2/connect-campaign-call")

        logger.info("Connecting to campaign '%s' (id: %s).", campaign.name, campaign.id)
        try:
            with GuavaSocket[guavadialer_events.ClientMessage, guavadialer_events.ServerMessage](
                    "serve-campaign",
                    self._client.get_websocket_url(f"v1/serve-campaign/{campaign.id}"),
                    headers=self._client._get_headers(),
                    serializer=lambda msg: msg.model_dump(),
                    deserializer=guavadialer_events.decode_server_message,
                ) as gs:

                active_call_threads: list[threading.Thread] = []

                def poll_campaign_completion():
                    """Poll campaign status and close the socket when no callable contacts remain and no local calls are active."""
                    while gs.is_open():
                        time.sleep(5)
                        try:
                            r = httpx.get(
                                self._client.get_http_url(f"v1/campaigns/{campaign.id}/has-callable-contacts"),
                                headers=self._client._get_headers(),
                            )
                            check_response(r)
                            if not r.json().get("has_callable_contacts", True):
                                # Wait for any local call threads to finish before closing.
                                alive = [t for t in active_call_threads if t.is_alive()]
                                if alive:
                                    logger.info("Campaign '%s' has no more callable contacts, but %d call(s) still active locally. Waiting.", campaign.name, len(alive))
                                    continue
                                logger.info("Campaign '%s' has no more callable contacts and no active calls. Closing.", campaign.name)
                                gs.close()
                                return
                        except Exception:
                            logger.debug("Failed to poll campaign status, will retry.", exc_info=True)

                threading.Thread(target=poll_campaign_completion, daemon=True).start()

                while gs.is_open():
                    server_message = gs.recv()
                    match server_message:
                        case guavadialer_events.ListenStarted():
                            logger.info("Listening for calls on campaign '%s' (controller mode). Ready.", campaign.name)
                        case guavadialer_events.InitiateAndAssignCall():
                            # Only used in controller mode. In headless mode the server handles calls directly.
                            log_phone = server_message.contact_data.get('phone_number') if server_message.contact_data else '?'
                            logger.info("Ready to make call, id %s — running precall for contact %s.", server_message.call_id, log_phone)
                            t = threading.Thread(
                                target=initiate_call,
                                args=(server_message.call_id, server_message.contact_data),
                                daemon=True,
                            )
                            active_call_threads.append(t)
                            t.start()
        except GuavaSocketClosedError:
            logger.info("Campaign '%s' disconnected.", campaign.name)

    def attach_campaign(
        self,
        *,
        campaign: campaigns.Campaign,
    ) -> None:
        self._serve_campaign(campaign)
