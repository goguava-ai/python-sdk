from typing import Optional, Literal, Union, Annotated
from pydantic import BaseModel, Field, model_validator, JsonValue
from .types import E164PhoneNumber, ActionItem, Language, DTMFDigit

class StartOutboundCallCommand(BaseModel):
    command_type: Literal["start-outbound"] = "start-outbound"

    from_number: Optional[E164PhoneNumber]
    to_number: E164PhoneNumber

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
    completion_criteria: Optional[str] = None
    action_items: list[ActionItem]


class ReadScriptCommand(BaseModel):
    command_type: Literal["read-script"] = "read-script"
    script: str


class AnswerQuestionCommand(BaseModel):
    command_type: Literal["answer-question"] = "answer-question"
    question_id: str
    answer: str

class ActionCandidate(BaseModel):
    key: str
    description: str = ''

class ActionSuggestionCommand(BaseModel):
    command_type: Literal["action-suggestion"] = "action-suggestion"
    intent_id: str
    # Legacy fields for unambiguous intents, preserved so older SDKs keep working.
    action_key: Optional[str] = None
    action_description: str = ''
    # Empty list = no match. One element = single unambiguous intent. Multiple = ambiguous intent.
    actions: list[ActionCandidate] = Field(default_factory=list)

    # Populate actions from action_key/description for legacy sdks
    @model_validator(mode="after")
    def _normalize(self):
        if not self.actions and self.action_key is not None:
            self.actions = [ActionCandidate(key=self.action_key, description=self.action_description)]
        return self

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
    has_on_escalate: bool = False
    accept_dtmf_for_numbers: bool = True

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

class RetryTaskCommand(BaseModel):
    command_type: Literal['retry-task'] = 'retry-task'
    reason: str
    
class SetVariableCommand(BaseModel):
    command_type: Literal["set-variable"] = 'set-variable'
    key: str
    value: JsonValue

class SendCallerTextCommand(BaseModel):
    command_type: Literal["send-caller-text"] = "send-caller-text"
    text: str

class ExpertErrorCommand(BaseModel):
    """
    Use this message to inform the Agent when the expert has errored
    while processing a callback.
    """

    command_type: Literal["expert-error"] = 'expert-error'
    message: str

class SetAgentDTMFCommand(BaseModel):
    """Enable or disable the agent's ability to press DTMF digits."""
    command_type: Literal["set-agent-dtmf"] = 'set-agent-dtmf'
    enabled: bool

class SendAgentDTMFCommand(BaseModel):
    """
    Command to press DTMF digits non-agentically
    """
    command_type: Literal["send-agent-dtmf"] = 'send-agent-dtmf'
    digits: list[DTMFDigit]

Command = Annotated[
    Union[
        StartOutboundCallCommand,
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
        RetryTaskCommand,
        SetVariableCommand,
        SendCallerTextCommand,
        ExpertErrorCommand,
        SetAgentDTMFCommand,
        SendAgentDTMFCommand, 
    ],
    Field(discriminator="command_type"),
]

class InboundTunnelCommand(BaseModel):
    call_id: str
    command: Command
