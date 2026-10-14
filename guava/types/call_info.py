from typing import Annotated, Literal, Optional, Union
from pydantic import BaseModel, Field, JsonValue
from guava.types import E164PhoneNumber


class PSTNCallInfo(BaseModel):
    call_type: Literal["pstn"] = "pstn"

    # The from_number for a PSTN call is not always known due to anonymous calls, e.g. *67 on T-mobile
    # You have the option to deny those calls if you want.
    from_number: E164PhoneNumber | None

    to_number: E164PhoneNumber
    caller_id: Optional[str] = None


class WebRTCCallInfo(BaseModel):
    call_type: Literal["webrtc"] = "webrtc"
    webrtc_code: str
    custom_payload: dict[str, JsonValue] = {}


class SipCallInfo(BaseModel):
    call_type: Literal["sip"] = "sip"

    from_aor: str = Field(
        description='Despite the name, this field contains the entire SIP from-spec value, not just the AOR. Example: `"Display Name" <sip:user@example.com:5060>;tag=abc123`.'
    )

    sip_code: Optional[str] = None
    sip_headers: dict[str, str] = {}

    @property
    def from_uri(self) -> str:
        """The from URI."""
        value = self.from_aor.strip()

        # Skip a quoted display name, which may contain '<', '>' or escaped quotes.
        i = 0
        if value.startswith('"'):
            i = 1
            while i < len(value) and value[i] != '"':
                i += 2 if value[i] == "\\" else 1
            i += 1

        # A '<' after the first ';' is inside a header param, not the URI's bracket.
        start = value.find("<", i)
        semi = value.find(";", i)
        if start != -1 and (semi == -1 or start < semi):
            end = value.find(">", start)
            if end != -1:
                return value[start + 1 : end].strip()

        return value.split(";", 1)[0].strip()


CallInfo = Annotated[
    Union[
        PSTNCallInfo,
        WebRTCCallInfo,
        SipCallInfo,
    ],
    Field(discriminator="call_type"),
]
