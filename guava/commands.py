from typing import Optional, Literal, Union, Annotated
from pydantic import BaseModel, Field, model_validator, JsonValue
from .types import E164PhoneNumber, ActionItem, Language

class StartOutboundCallCommand(BaseModel):
    command_type: Literal["start-outbound"] = "start-outbound"

    from_number: Optional[E164PhoneNumber]
    to_number: E164PhoneNumber

class ReconnectOutboundSessionCommand(BaseModel):
    command_type: Literal["reconnect-outbound"] = "reconnect-outbound"
    session_id: str
    highest_seen_sequence: int


class ListenInboundCommand(BaseModel):
    command_type: Literal["listen-inbound"] = "listen-inbound"
    agent_number: Optional[E164PhoneNumber] = None
    webrtc_code: Optional[str] = None
    sip_code: Optional[str] = None
    
    @model_validator(mode="after")
    def _require_inbound_target(self):
        if self.agent_number is None and self.webrtc_code is None and self.sip_code is None:
            raise ValueError("One of 'agent_number', 'webrtc_code', or 'sip_code' must be set.")
        return self

class RejectInboundCallCommand(BaseModel):
    command_type: Literal["reject-inbound"] = "reject-inbound"


class AcceptInboundCallCommand(BaseModel):
    command_type: Literal["accept-inbound"] = "accept-inbound"


class SetTaskCommand(BaseModel):
    command_type: Literal["set-task"] = "set-task"
    task_id: str
    objective: str
    success_criteria: Optional[str] = None
    action_items: list[ActionItem]


class ReadScriptCommand(BaseModel):
    command_type: Literal["read-script"] = "read-script"
    script: str


class AnswerQuestionCommand(BaseModel):
    command_type: Literal["answer-question"] = "answer-question"
    question_id: str
    answer: str

class ActionSuggestionCommand(BaseModel):
    command_type: Literal["action-suggestion"] = "action-suggestion"
    intent_id: str
    action_key: Optional[str] # The key of the task that should be performed based on this intent
    action_description: str = ''

class SetPersona(BaseModel):
    command_type: Literal["set-persona"] = "set-persona"
    agent_name: Optional[str] = None
    organization_name: Optional[str] = None
    agent_purpose: Optional[str] = None
    voice: Optional[str] = None

class SetLanguageMode(BaseModel):
    command_type: Literal["set-language-mode"] = "set-language-mode"
    primary: Language = "english"
    secondary: list[Language] = Field(default_factory=list)
    
class RegisteredHooksCommand(BaseModel):
    command_type: Literal["registered-hooks"] = "registered-hooks"
    has_on_question: bool
    has_on_intent: bool
    has_on_action_requested: bool = False

class SendInstructionCommand(BaseModel):
    command_type: Literal["send-instruction"] = "send-instruction"
    instruction: str

class TransferCommand(BaseModel):
    command_type: Literal["transfer-call"] = 'transfer-call'
    transfer_message: str
    to_number: str
    soft_transfer: bool = False

class ChoiceResultCommand(BaseModel):
    command_type: Literal["choice-query-result"] = 'choice-query-result'
    field_key: str
    query_id: str
    matched_choices: list[str]
    other_choices: list[str]

class SetVariableCommand(BaseModel):
    command_type: Literal["set-variable"] = 'set-variable'
    key: str
    value: JsonValue

Command = Annotated[
    Union[
        StartOutboundCallCommand,
        ReconnectOutboundSessionCommand,
        RegisteredHooksCommand,
        AnswerQuestionCommand,
        ActionSuggestionCommand,
        ReadScriptCommand,
        ListenInboundCommand,
        SetTaskCommand,
        RejectInboundCallCommand,
        AcceptInboundCallCommand,
        SetPersona,
        SendInstructionCommand,
        TransferCommand,
        ChoiceResultCommand,
        SetLanguageMode,
        SetVariableCommand,
    ],
    Field(discriminator="command_type"),
]

class InboundTunnelCommand(BaseModel):
    call_id: str
    command: Command
