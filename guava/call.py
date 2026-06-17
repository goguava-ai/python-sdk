import json
import logging
import queue


from .commands import (
    Command,
    SetTaskCommand,
    SetPersona,
    SendInstructionCommand,
    TransferCommand,
    RetryTaskCommand,
    SetVariableCommand,
    SetLanguageMode,
    ReadScriptCommand,
    SetAgentDTMFCommand,
)
from . import types
from .types import Field, Say

from typing import Optional, Union, Any
from guava.types import Language
from guava.telemetry import telemetry_client
from guava.call_controller import CommandQueueEnd
from guava.utils import is_jsonable
from pydantic import BaseModel
from guava.types.call_info import CallInfo

logger = logging.getLogger("guava.call")

class ReachPersonOutcome(BaseModel):
    """
    Defines a possible outcome when attempting to reach a contact.

    Attributes:
        key: Unique identifier for this outcome (e.g., 'available', 'wrong_number').
        description: Optional human-readable description of what this outcome represents.
        next_action_preview: Optional preview of the next action in 2nd person, starting with
            a verb (e.g., "pull up the first question", "record their response"). This helps
            the LLM transition smoothly by saying "Let me just [next_action_preview]" instead
            of awkwardly stalling.
    """
    key: str
    description: Optional[str] = None
    next_action_preview: Optional[str] = None

DEFAULT_REACH_PERSON_OUTCOMES: list[ReachPersonOutcome] = [
    ReachPersonOutcome(key='available',      description='The intended contact is confirmed on the line.'),
    ReachPersonOutcome(key='unavailable',    description='The contact could not be reached. A third party, gatekeeper, or IVR was unable to transfer the call to the contact.'),
    ReachPersonOutcome(key='voicemail',      description='An answering machine or voicemail system was reached.'),
    ReachPersonOutcome(key='wrong_number',   description='The number does not reach the intended contact.'),
    ReachPersonOutcome(key='do_not_contact', description='The person on the line has indicated this number should not be called.'),
]

def _voicemail_hangup_instruction() -> str:
    return "DO NOT leave a message. REMAIN SILENT AND HANG UP WITHOUT RESPONDING."

def _voicemail_message_instruction(message: str) -> str:
    return f"Say this message VERBATIM: \"{message}\" Then hang up."


@telemetry_client.track_class()
class Call:
    def __init__(self, session_id: str, call_info: CallInfo) -> None:
        self._session_id = session_id
        self._call_info = call_info

        self._command_queue: queue.Queue[Command | CommandQueueEnd] = queue.Queue()
        self._field_values: dict[str, Any] = {}
        self._variables: dict[str, Any] = {}

    @property
    def id(self) -> str:
        return self._session_id
    
    @property
    def call_info(self) -> CallInfo:
        return self._call_info

    def set_variable(self, key: str, value: Any) -> None:
        if not is_jsonable(value):
            raise ValueError(f"Variable value for key '{key}' must be JSON-serializable.")
        self._variables[key] = value
        self.send_command(SetVariableCommand(
            key=key,
            value=value
        ))

    def get_variable(self, key: str, default: Any = None) -> Any:
        return self._variables.get(key, default)

    set_var = set_variable
    get_var = get_variable

    def set_language_mode(
            self,
            primary: Language = "english",
            secondary: Optional[list[Language]] = None,
    ):
        self.send_command(
            SetLanguageMode(
                primary=primary,
                secondary=secondary or [],
            )
        )

    def set_agent_dtmf(self, enabled: bool):
        self.send_command(SetAgentDTMFCommand(enabled=enabled))

    def set_persona(
            self,
            organization_name: Optional[str] = None,
            agent_name: Optional[str] = None,
            agent_purpose: Optional[str] = None,
            voice: Optional[str] = None
    ):
        self.send_command(
            SetPersona(
                organization_name=organization_name,
                agent_name=agent_name,
                agent_purpose=agent_purpose,
                voice=voice
            )
        )

    def set_voicemail_action(self, hangup: bool = False, message: str | None = None):
        """
        Instruct the bot how to handle an answering machine or voicemail system.

        If you are using reach_person(), use the voicemail_message or voicemail_hangup
        parameters there instead — they integrate voicemail as a tracked outcome so
        on_reach_person fires correctly.
        """
        if self.get_variable("_voicemail_handler") == "reach_person":
            raise ValueError(
                "Cannot call set_voicemail_action() after reach_person(). "
                "Use the voicemail_message or voicemail_hangup parameters on reach_person() instead."
            )
        self.set_variable("_voicemail_handler", "set_voicemail_action")

        if hangup and message:
            raise ValueError("Cannot specify both 'hangup' and 'message'.")
        if not hangup and not message:
            raise ValueError("Must specify either 'hangup' or 'message'.")
        
        if hangup:
            self.send_instruction(f"If you encounter an answering machine, {_voicemail_hangup_instruction()} You should only do this when it's clear you are unable to reach the person.")

        if message:
            self.send_instruction(f"If you encounter an answering machine, {_voicemail_message_instruction(message)} You should only do this when it's clear you are unable to reach the person.")

    def send_command(self, command: Command):
        self._command_queue.put(command)
        logger.debug("Command queued: %r", command)

    def get_field(self, field_key: str, default: Any = None) -> Any:
        return self._field_values.get(field_key, default)

    def has_field(self, field_key: str) -> bool:
        return field_key in self._field_values

    def transfer(self, destination: str, instructions: str | None = None):
        # TODO: Verify that destination is a phone number or SIP address.
        self.send_command(
            TransferCommand(
                transfer_message=instructions or "Notify the caller that you will be transferring them, and then transfer.",
                to_number=destination,
                soft_transfer=True
            )
        )

    def set_task(
        self,
        task_id: str,
        objective: str = "",
        checklist: Optional[list[Union[Field, Say, str]]] = None,
        completion_criteria: Optional[str] = "",
    ):
        assert objective or checklist, "At least one of args ['objective','checklist'] must be provided."

        checklist = checklist or []

        action_items : list[Union[types.Todo, types.SerializableField, Say]] = []
        for item in checklist:
            if isinstance(item, str):
                action_items.append(types.Todo(item))
            elif isinstance(item, Field):
                if item.choice_generator:
                    raise NotImplementedError("choice_generator is not compatible with the Agent / Call API. Use searchable=True and register a handler.")
                
                action_items.append(types.SerializableField(
                    item_type=item.item_type,
                    key=item.key,
                    description=item.description,
                    question=item.question,
                    field_type=item.field_type,
                    required=item.required,
                    choices=item.choices,
                    is_search_field=item.searchable
                ))
            else:
                action_items.append(item)

        self.send_command(
            SetTaskCommand(
                task_id=task_id,
                objective=objective,
                action_items=action_items,
                completion_criteria=completion_criteria,
            )
        )

    def retry_task(self, reason: str):
        self.send_command(RetryTaskCommand(reason=reason))

    def read_script(self, script: str):
        self.send_command(ReadScriptCommand(script=script))

    def add_info(self, label: str, info: Any):
        self.send_instruction(f"Here is some information about the following topic {label}:\n{json.dumps(info, indent=2)}")

    def send_instruction(self, instruction: str):
        self.send_command(SendInstructionCommand(instruction=instruction))

    def hangup(self, final_instructions: str =''):
        if final_instructions:
            instructions = f"Start ending the conversation. Here are your final instructions: {final_instructions} Once you've completed the final instructions, naturally end the conversation and hang up the call."
        else:
            instructions = "Naturally end the conversation and hang up the call."
        self.send_instruction(instructions)


    def _shutdown_queue(self):
        self._command_queue.put(CommandQueueEnd())


    def reach_person(
        self,
        contact_full_name: str,
        *,
        greeting: str | None = None,
        voicemail_message: str | None = None,
        voicemail_hangup: bool = False,
        outcomes: list[ReachPersonOutcome] | None = None,
    ):
        """
        Helper for reaching a specific contact on an outbound call and recording their
        availability. Defined in terms of set_task - use set_task directly for fully
        custom scenarios.

        Args:
            contact_full_name: The name of the person to reach.
            greeting: If provided, the bot reads this verbatim as its opening.
            voicemail_message: If voicemail is reached, leave this message verbatim then hang up.
            voicemail_hangup: If True, hang up immediately when voicemail is reached
                without leaving a message.
            outcomes: Override the set of possible contact_availability outcomes. Defaults to
                DEFAULT_REACH_PERSON_OUTCOMES. To extend the defaults, pass
                DEFAULT_REACH_PERSON_OUTCOMES + [ReachPersonOutcome(...)].
        """
        outcomes = outcomes or DEFAULT_REACH_PERSON_OUTCOMES

        # Build choice descriptions for the Multiple Choice field.
        availability_field_description = f"The availability of {contact_full_name}."
        choice_lines = [
            f" - {outcome.key}: {outcome.description}" 
            for outcome in outcomes
            if outcome.description is not None
        ]
        if choice_lines:
            availability_field_description += (
                "\nDetailed descriptions of each choice:\n" + "\n".join(choice_lines)
            )


        # Define voicemail action.
        if self.get_variable("_voicemail_handler") == "set_voicemail_action":
            raise ValueError(
                "Cannot call reach_person() after set_voicemail_action(). "
                "Use the voicemail_message or voicemail_hangup parameters on reach_person() instead."
            )
        self.set_variable("_voicemail_handler", "reach_person")

        if voicemail_message and voicemail_hangup:
            raise ValueError("Cannot specify both 'voicemail_message' and 'voicemail_hangup'.")

        # Build the voicemail instruction for the objective.
        if voicemail_hangup:
            voicemail_rule = _voicemail_hangup_instruction()
        elif voicemail_message:
            voicemail_rule = _voicemail_message_instruction(voicemail_message)
        else:
            voicemail_rule = "Leave an appropriate voicemail message."

        # Define objective.
        objective = f"""
OBJECTIVE:
Your goal is to reach {contact_full_name} and confirm they are on the line.

RULES:
1. If someone other than {contact_full_name} answers - including a person or IVR:
   - Politely ask to speak with {contact_full_name}, or navigate menus and prompts to reach them.
   - Wait to be transferred or for {contact_full_name} to come to the phone.
   - If {contact_full_name} cannot be reached, record `contact_availability` appropriately.
2. Once {contact_full_name} is confirmed on the line:
   - Briefly restate who you are and the purpose of your call
   - Record their availability as available, or equivalent, in `contact_availability`.
3. If it is clearly a wrong number or you have been asked not to call, politely end the call and hang up.
4. If you reach an answering machine or voicemail: {voicemail_rule}
"""

        completion_criteria = f"""
TASK COMPLETION REQUIREMENTS:
- The availability of {contact_full_name} must be recorded in `contact_availability`.
"""

        # Build checklist.
        checklist = [
            Say(greeting) if greeting is not None
            else f"Greet the person, IVR, or system who answered the phone. "
                 f"Notify them who you are calling on behalf of and the purpose of the call. "
                 f"Ask to speak with {contact_full_name}. "
                 f"Do not greet if you detect an answering machine or voicemail system.",
            Field(
                key='contact_availability',
                description=availability_field_description,
                field_type='multiple_choice',
                choices=[outcome.key for outcome in outcomes],
                required=True,
            )
        ]

        # Append transition instructions for any outcomes that define a next_action_preview.
        next_action_lines = [
            f"- {outcome.key} → {outcome.next_action_preview}"
            for outcome in outcomes
            if outcome.next_action_preview is not None
        ]
        if next_action_lines:
            checklist.append(
                "If a next action is defined below for the recorded value of `contact_availability`, "
                "briefly let the contact know while you perform it.\n"
                + "\n".join(next_action_lines)
            )

        # Set the "Reach Person" task.
        self.set_task("reach_person", objective, checklist, completion_criteria)
