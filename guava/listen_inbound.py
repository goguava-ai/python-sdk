
"""
This is the protocol for inbound listeners. Inbound listening consists of a two-stage process:
1 - Receive notification of an inbound call, and attempt to claim it for this listener.
2 - Once the server has assigned the call to you, you may answer and connect a controller, or decline the call.
"""

from pydantic import BaseModel, TypeAdapter
from typing import Literal
from guava.types.call_info import CallInfo

class ListenStarted(BaseModel):
    message_type: Literal["listen-started"] = "listen-started"
    other_listeners: int
    
    
class IncomingCall(BaseModel):
    """
    This message is sent from the server when an inbound call is received.
    The listener should either remain silent or attempt to claim the call.
    """
    message_type: Literal["incoming-call"] = "incoming-call"
    call_id: str
    
class ClaimCall(BaseModel):
    """
    The listener sends this to the server to attempt to claim the call for itself.
    """
    message_type: Literal["claim-call"] = "claim-call"
    call_id: str
    
class AssignCall(BaseModel):
    message_type: Literal["assign-call"] = "assign-call"
    call_id: str
    call_info: CallInfo


class AnswerCall(BaseModel):
    message_type: Literal["answer-call"] = "answer-call"
    call_id: str

class DeclineCall(BaseModel):
    message_type: Literal["decline-call"] = "decline-call"
    call_id: str
    
    
ServerMessage = ListenStarted | IncomingCall | AssignCall
ClientMessage = ClaimCall | AnswerCall | DeclineCall

def decode_server_message(payload: dict) -> ServerMessage:
    return TypeAdapter(ServerMessage).validate_python(payload)