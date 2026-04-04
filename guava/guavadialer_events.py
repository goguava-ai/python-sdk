from pydantic import BaseModel, TypeAdapter
from typing import Literal, Any


class ListenStarted(BaseModel):
    message_type: Literal["listen-started"] = "listen-started"
    other_listeners: int
    
    
class InitiateAndAssignCall(BaseModel):
    """
    This message is sent from the server when it wants to start a call,
    and when it's assigned it to the appropriate pod.
    """
    message_type: Literal["initiate-and-assign-call"] = "initiate-and-assign-call"                                                                                                                                                                                                        
    call_id: str
    contact_data: Any  # whatever the developer put in Contact.data at upload time     

class ControllerReady(BaseModel):
    """
    This message is sent from the client back to the server when it's initiated a call
    controller and is therefore ready to connect to the call.
    """
    message_type: Literal["controller-ready"] = "controller-ready"
    call_id: str


class InitControllerFailed(BaseModel):
    """
    This message is sent from the client when the controller failed to initialize (e.g. timeout).
    The server should release any resources held for this call.
    """
    message_type: Literal["init-controller-failed"] = "init-controller-failed"
    call_id: str



ServerMessage = ListenStarted | InitiateAndAssignCall
ClientMessage = ControllerReady | InitControllerFailed

def decode_server_message(payload: dict) -> ServerMessage:
    return TypeAdapter(ServerMessage).validate_python(payload)