from typing import Annotated, Literal, Optional, Union
from pydantic import BaseModel, Field
from guava.types import E164PhoneNumber

class PSTNCallInfo(BaseModel):
	call_type: Literal["pstn"] = 'pstn'

	# The from_number for a PSTN call is not always known due to anonymous calls, e.g. *67 on T-mobile
	# You have the option to deny those calls if you want.
	from_number: E164PhoneNumber | None

	to_number: E164PhoneNumber
	caller_id: Optional[str] = None
	
class WebRTCCallInfo(BaseModel):
	call_type: Literal["webrtc"] = 'webrtc'
	webrtc_code: str
	
class SipCallInfo(BaseModel):
	call_type: Literal["sip"] = "sip"
	from_aor: str
	sip_code: Optional[str] = None
	sip_headers: dict[str, str] = {}


CallInfo = Annotated[
    Union[
        PSTNCallInfo,
        WebRTCCallInfo,
        SipCallInfo,
    ],
    Field(discriminator="call_type"),
]
