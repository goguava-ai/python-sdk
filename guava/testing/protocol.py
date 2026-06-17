from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field


class Ping(BaseModel):
    message_type: Literal["ping"] = "ping"


class Pong(BaseModel):
    message_type: Literal["pong"] = "pong"


class InjectASR(BaseModel):
    message_type: Literal["inject-asr"] = "inject-asr"
    utterance: str


class WaitForTurn(BaseModel):
    message_type: Literal["wait-for-caller-turn"] = "wait-for-caller-turn"
    request_id: str


TestingCommand = Annotated[
    Union[InjectASR, Ping, Pong, WaitForTurn],
    Field(discriminator="message_type"),
]


class TurnStarted(BaseModel):
    message_type: Literal["caller-turn-started"] = "caller-turn-started"
    request_id: str


class SessionStarted(BaseModel):
    message_type: Literal["session-started"] = "session-started"
    session_id: str


class BotTTS(BaseModel):
    message_type: Literal["bot-tts"] = "bot-tts"
    transcript: str


TestingEvent = Annotated[
    Union[Ping, Pong, BotTTS, TurnStarted],
    Field(discriminator="message_type"),
]
