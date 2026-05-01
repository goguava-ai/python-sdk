import logging
import threading
import os
import httpx
import platform
import warnings
import sys
from queue import Empty

from .events import (
    InboundCallEvent,
    Event,
    OutboundCallFailed,
    BotSessionEnded,
    decode_event_dict,
)
from .commands import (
    Command,
)

from typing import Optional, TypeVar, Type, Callable, Any, TYPE_CHECKING
from urllib.parse import urljoin, urlencode
from .call_controller import CallController, CommandQueueEnd

from importlib.metadata import version, PackageNotFoundError
from .threading_utils import FirstEntry

from guava.socket.client import GuavaSocket, GuavaSocketClosedError
from . import listen_inbound, guavadialer_events
from .utils import get_base_url, check_exactly_one, check_response, preview
from .telemetry import telemetry_client
from guava.types.call_info import CallInfo, PSTNCallInfo
from datetime import timedelta

if TYPE_CHECKING:
    from . import campaigns

SDK_NAME = "python-sdk"
try:
    __version__ = version("guava-sdk")
except PackageNotFoundError:
    __version__ = "0+unknown"


logger = logging.getLogger("guava")


U = TypeVar("U", bound=CallController)

first_client = FirstEntry()

@telemetry_client.track_class()
class Client:
    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None):
        if base_url:
            self._base_url = base_url
        else:
            self._base_url = get_base_url()

        if api_key:
            self._api_key = api_key
        elif 'GUAVA_API_KEY' in os.environ:
            self._api_key = os.environ['GUAVA_API_KEY']
        else:
            raise Exception("Guava API key must be provided either as argument to client constructor, or in environment variable GUAVA_API_KEY.")
        
        if first_client.claim():
            # Set SDK headers for telemetry uploads.
            telemetry_client.set_sdk_headers(self._get_headers())

            logger.debug("Checking deprecation for SDK %s, %s.", SDK_NAME, __version__)
            try:
                r = httpx.post(self.get_http_url("v1/check-sdk-deprecation"), params={
                    "sdk_name": SDK_NAME,
                    "sdk_version": __version__
                })
                check_response(r)
                deprecation_info = r.json()
                
                match deprecation_info["deprecation_status"]:
                    case "supported":
                        logger.info("SDK version still supported.")
                    case "deprecated":
                        warnings.warn("This SDK version is deprecated. Please update to a newer version of the SDK.", UserWarning, stacklevel=3)
                    case _:
                        logger.warning("SDK deprecation status unknown.")
            except Exception:
                logger.exception("Encountered issue while checking for deprecation.")

    def _get_http_base(self) -> str:
        return self._base_url
    
    def _get_websocket_base(self) -> str:
        if self._base_url.startswith("http://"):
            return "ws://" + self._base_url[len("http://"):]
        elif self._base_url.startswith("https://"):
            return "wss://" + self._base_url[len("https://"):]
        else:
            raise Exception("Invalid base URL: " + self._base_url)
        
    def get_http_url(self, path: str) -> str:
        return urljoin(self._get_http_base(), path)
    
    def get_websocket_url(self, path: str) -> str:
        return urljoin(self._get_websocket_base(), path)

    def _get_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "x-guava-platform": platform.system(),
            "x-guava-runtime": platform.python_implementation(),
            "x-guava-runtime-version": platform.python_version(),
            "x-guava-sdk": SDK_NAME,
            "x-guava-sdk-version": __version__,
        }
    
    def create_webrtc_agent(self, ttl: timedelta | None = None) -> str:
        query = {}
        if ttl:
            query["ttl_sec"] = ttl.total_seconds()

        r = httpx.post(self.get_http_url("v1/webrtc-agents"), params=query, headers=self._get_headers())
        check_response(r)
        return r.json()['webrtc_code']

    def create_sip_agent(self) -> str:
        r = httpx.post(self.get_http_url("v1/sip-agents"), headers=self._get_headers())
        check_response(r)
        return r.json()['sip_code']

    def create_outbound(
        self,
        *,
        from_number: str,
        to_number: str,
        call_controller: CallController,
    ):
        """
        Create an outbound phone call, and attach the given call controller.
        """
        response = check_response(httpx.post(
            self.get_http_url("v2/create-outbound"),
            headers=self._get_headers(),
            params={
                "from_number": from_number,
                "to_number": to_number
            }
        ))
        call_id = response.json()["call_id"]
        logger.info("Outbound call created with session ID: %s", call_id)
        self._attach_to_call(call_id, call_controller)

    @preview("Terminal Calling")
    def terminal_call(self, call_controller: U):
        import importlib.util

        # First check that required deps are available.
        required_packages = ["aiortc", "sounddevice", "numpy"]
        needed_packages = [pkg for pkg in required_packages if importlib.util.find_spec(pkg) is None]

        if needed_packages:
            print("Terminal calling requires the following additional dependencies to be installed:", needed_packages)
            print("- To install using pip, run: pip install " + ' '.join(needed_packages))
            print("- To install using uv, run: uv add " + ' '.join(needed_packages))
            sys.exit(1)
        
        import asyncio
        from .terminal_call import TerminalCall
        webrtc_code = self.create_webrtc_agent()

        listen_thread = threading.Thread(target=self.listen_inbound, kwargs={
            'webrtc_code': webrtc_code,
            'controller_factory': lambda _: call_controller
        }, daemon=True)
        listen_thread.start()
        asyncio.run(TerminalCall(self, webrtc_code).start())

    def _attach_to_call(self, call_id: str, call_controller: U):
        """Attach a call controller to a given call ID."""
        try:
            command_thread = None
            
            with GuavaSocket[Command, Event | None](
                    f"call-connection-{call_id}",
                    self.get_websocket_url(f"v2/connect-call/{call_id}"), 
                    headers=self._get_headers(),
                    serializer=lambda command: command.model_dump(),
                    deserializer=lambda e: decode_event_dict(e),
                    max_age_seconds=18000 # Conservatively kill the connection after 5 hours.
                ) as gs:
                
                def drain_commands():
                    while gs.is_open():
                        command: Command | CommandQueueEnd = call_controller._command_queue.get(block=True)
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
                    
                    if isinstance(event, OutboundCallFailed) or isinstance(event, BotSessionEnded):
                        # These two events get run on the main thread
                        call_controller.on_event(event)
                    else:
                        # Run event on it's own thread, to allow for awaiting. This could be made a threadpool, but you could
                        # still exhaust the pool with a bunch of await tasks, and thus deadlock a controller.
                        threading.Thread(target=call_controller.on_event, args=(event,), daemon=True).start()

                    if isinstance(event, OutboundCallFailed) or isinstance(event, BotSessionEnded):
                        # These events are considered terminal, and should signal the call controller to shutdown.
                        break
        finally:
            call_controller.shutdown()
            if command_thread:
                command_thread.join()
                
            logger.debug("Call controller succesfully shut down...")
            

    def listen_inbound(self, *, agent_number: str | None = None, webrtc_code: str | None = None, sip_code: str | None = None, controller_class: Type[U] | None = None, controller_factory: Callable[[CallInfo], U | None] | None = None):
        if not check_exactly_one(agent_number, webrtc_code, sip_code):
            raise TypeError("One of agent_number, webrtc_code, or sip_code must be provided.")
        
        if not check_exactly_one(controller_class, controller_factory):
            raise TypeError("One of controller_class or controller_factory must be provided.")
        
        assert controller_class or controller_factory # For the type checker.
        
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
                self.get_websocket_url(f"v2/listen-inbound?{query_string}"),
                headers=self._get_headers(),
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
                            logger.info("WebRTC URL: %s?webrtc_code=%s", self.get_http_url('debug-webrtc'), webrtc_code)
                        elif sip_code:
                            logger.info("Started listening on SIP code %s. %d other listeners registered.", sip_code, server_message.other_listeners)
                    case listen_inbound.IncomingCall():
                        gs.send(listen_inbound.ClaimCall(call_id=server_message.call_id))
                    case listen_inbound.AssignCall():
                        logger.info("Received call (session ID: %s), info: %r", server_message.call_id, server_message.call_info)
                        try:
                            if controller_class:
                                call_controller = controller_class()
                            elif controller_factory:
                                call_controller = controller_factory(server_message.call_info)

                            if call_controller:
                                logger.info("Answering call...")
                                gs.send(listen_inbound.AnswerCall(call_id=server_message.call_id))
                                threading.Thread(target=self._attach_to_call, args=(server_message.call_id, call_controller), daemon=True).start()

                                # Still invoke this callback even though it is considered deprecated. It can no longer be used to decline incoming calls.
                                event = InboundCallEvent(caller_number=server_message.call_info.from_number if isinstance(server_message.call_info, PSTNCallInfo) else None)
                                threading.Thread(target=call_controller.on_event, args=(event,), daemon=True).start()
                            else:
                                logger.info("Call controller factory returned None... Declining call...")
                                gs.send(listen_inbound.DeclineCall(call_id=server_message.call_id))
                        except Exception:
                            logger.exception("Failed to initialize call controller.")


    # this is the one the client calls. it hits the endpoint that creates the websocket and its handler...
    def serve_campaign(
        self,
        *,
        campaign: "campaigns.Campaign",
        controller: Type[U],
    ):
        init_timeout: float = 5.0

        def initiate_call_controller(call_id: str, contact_data: Any):
            data = contact_data.get('data') if contact_data else None
            call_controller = None

            def init_controller():
                nonlocal call_controller
                call_controller = controller(data=data)

            init_thread = threading.Thread(target=init_controller, daemon=True)
            init_thread.start()
            init_thread.join(timeout=init_timeout)
            if init_thread.is_alive() or call_controller is None:
                logger.error("Call %s: controller init timed out after %.1f seconds. Rescheduling contact.", call_id, init_timeout)
                gs.send(guavadialer_events.InitControllerFailed(call_id=call_id))
                return

            logger.info("Call %s: controller ready.", call_id)
            gs.send(guavadialer_events.ControllerReady(call_id=call_id))

            with GuavaSocket[Command, Event](
                    f"campaign-call-{call_id}",
                    self.get_websocket_url(f"v2/connect-campaign-call/{call_id}"),
                    headers=self._get_headers(),
                    serializer=lambda command: command.model_dump(),
                    deserializer=lambda e: decode_event_dict(e),
                    max_age_seconds=18000,
                ) as call_gs:

                def listen_for_events():
                    try:
                        while call_gs.is_open():
                            event = call_gs.recv()
                            if event:
                                threading.Thread(target=call_controller.on_event, args=(event,), daemon=True).start()
                                if isinstance(event, BotSessionEnded):
                                    call_controller.shutdown()
                    except GuavaSocketClosedError:
                        pass

                listen_events_thread = threading.Thread(target=listen_for_events, daemon=True)
                listen_events_thread.start()

                while call_gs.is_open():
                    try:
                        command = call_controller._command_queue.get(block=True, timeout=1)
                    except Empty:
                        continue
                    if isinstance(command, CommandQueueEnd):
                        break
                    logger.debug("Sending command: %r for call ID: %s", command, call_id)
                    call_gs.send(command)

                call_gs.close()
                listen_events_thread.join()

        campaign_id = campaign.id
        campaign_name = campaign.name
        logger.info("Connecting to campaign '%s' (id: %s).", campaign_name, campaign_id)
        try:
            with GuavaSocket[guavadialer_events.ClientMessage, guavadialer_events.ServerMessage](
                    "serve-campaign",
                    self.get_websocket_url(f"v1/serve-campaign/{campaign_id}"),
                    headers=self._get_headers(),
                    serializer=lambda msg: msg.model_dump(),
                    deserializer=guavadialer_events.decode_server_message,
                ) as gs:

                active_call_threads: list[threading.Thread] = []

                def poll_campaign_completion():
                    """Poll campaign status and close the socket when no callable contacts remain and no local calls are active."""
                    import time as _time
                    while gs.is_open():
                        _time.sleep(5)
                        try:
                            r = httpx.get(
                                self.get_http_url(f"v1/campaigns/{campaign_id}/has-callable-contacts"),
                                headers=self._get_headers(),
                            )
                            check_response(r)
                            if not r.json().get("has_callable_contacts", True):
                                # Wait for any local call threads to finish before closing.
                                alive = [t for t in active_call_threads if t.is_alive()]
                                if alive:
                                    logger.info("Campaign '%s' has no more callable contacts, but %d call(s) still active locally. Waiting.", campaign_name, len(alive))
                                    continue
                                logger.info("Campaign '%s' has no more callable contacts and no active calls. Closing.", campaign_name)
                                gs.close()
                                return
                        except Exception:
                            logger.debug("Failed to poll campaign status, will retry.", exc_info=True)

                threading.Thread(target=poll_campaign_completion, daemon=True).start()

                while gs.is_open():
                    server_message = gs.recv()
                    match server_message:
                        case guavadialer_events.ListenStarted():
                            logger.info("Listening for calls on campaign '%s' (controller mode). Ready.", campaign_name)
                        case guavadialer_events.InitiateAndAssignCall():
                            # Only used in controller mode. In headless mode the server handles calls directly.
                            log_phone = server_message.contact_data.get('phone_number') if server_message.contact_data else '?'
                            logger.info("Ready to make call, id %s — running precall for contact %s.", server_message.call_id, log_phone)
                            t = threading.Thread(
                                target=initiate_call_controller,
                                args=(server_message.call_id, server_message.contact_data),
                                daemon=True,
                            )
                            active_call_threads.append(t)
                            t.start()
        except GuavaSocketClosedError:
            logger.info("Campaign '%s' disconnected.", campaign_name)

    def send_sms(self, from_number: str, to_number: str, message: str) -> None:
        response = httpx.post(
            self.get_http_url("v1/send-sms"),
            json={
                "from_number": from_number,
                "to_number": to_number,
                "message": message,
            },
            headers=self._get_headers(),
        )
        check_response(response)
