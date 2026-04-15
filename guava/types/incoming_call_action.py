from typing import Annotated, Literal, Union
from pydantic import BaseModel, Field

class AcceptCall(BaseModel):
    call_action: Literal["accept"] = 'accept'

class DeclineCall(BaseModel):
    call_action: Literal['decline'] = 'decline'

IncomingCallAction = Annotated[
    Union[
        AcceptCall,
        DeclineCall,
    ],
    Field(discriminator="call_action"),
]
