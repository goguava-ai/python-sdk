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
)
from . import types
from .types import Field, Say

from typing import Optional, Union, Any
from guava.types import Language
from guava.telemetry import telemetry_client
from guava.call_controller import CommandQueueEnd
from guava.utils import is_jsonable
from pydantic import BaseModel

logger = logging.getLogger("guava.call")

class ReachPersonOutcome(BaseModel):
    """
    Defines a possible outcome when attempting to reach a contact.

    Attributes:
        key: Unique identifier for this outcome (e.g., 'contact_available', 'wrong_number')
        description: Optional human-readable description of what this outcome represents
        next_action_preview: Optional preview of the next action in 2nd person, starting with
            a verb (e.g., "pull up the first question", "record their response"). This helps
            the LLM transition smoothly by saying "Let me just [next_action_preview]" instead
            of awkwardly stalling.
    """
    key: str
    description: Optional[str] = None
    next_action_preview: Optional[str] = None


@telemetry_client.track_class()
class Call:
    def __init__(self) -> None:
        self._command_queue: queue.Queue[Command | CommandQueueEnd] = queue.Queue()
        self._field_values: dict[str, Any] = {}
        self._variables: dict[str, Any] = {}

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
        outcomes: list[ReachPersonOutcome] | None = None,
    ):
        """
        Helper function for reaching a specific contact on an outbound call and
        recording their availability. This helper is optional and provided as a convenience.
        It's defined in terms of call.set_task. Users can define their own client-side tasks to
        implement custom scenarios.
        """
        if not outcomes:
            outcomes = [
                ReachPersonOutcome(key='available', description="The contact is available to speak."),
                ReachPersonOutcome(key='unavailable', description="The contact is not available to speak. This includes reaching a wrong number."),
            ]

        # Build choice descriptions for the Multiple Choice field
        availability_field_description = f"The availability of {contact_full_name}"
        choice_lines = [
            f" - {outcome.key}: {outcome.description}" 
            for outcome in outcomes
            if outcome.description is not None
        ]
        if choice_lines:
            availability_field_description += (
                "\nDetailed descriptions of each choice:\n" + "\n".join(choice_lines)
            )


        # Define objective
        objective = f"""
OBJECTIVE:
Your goal is to reach {contact_full_name} and determine their availability to proceed with this call.

RULES:
1. If the initial respondent is NOT {contact_full_name}:
   - Politely ask to speak with {contact_full_name}
   - Wait to be transferred or for {contact_full_name} to come to the phone
2. Once you have {contact_full_name} on the line:
   - Briefly restate who you are and the purpose of your call
   - Determine and record their current availability status
3. DO NOT hang up the call under any circumstances, unless it's a wrong number.

TASK COMPLETION REQUIREMENTS:
- The availability of {contact_full_name} must be recorded in `contact_availability`.
"""

        # Build checklist
        checklist = [
            Say(greeting) if greeting is not None
            else f"Greet the person who answered the phone. "
                f"Notify them who you are calling on behalf of and the purpose of the call. "
                f"Ask to speak with {contact_full_name}",
            Field(
                key='contact_availability',
                description=availability_field_description,
                field_type='multiple_choice',
                choices=[outcome.key for outcome in outcomes],
                required=True,
            )
        ]

        # Optional transition instructions.
        next_action_lines = [
            f"- {outcome.key} → {outcome.next_action_preview}"
            for outcome in outcomes
            if outcome.next_action_preview is not None
        ]
        if next_action_lines:
            checklist.append(
                "If a next action is defined below for the value of `contact_availability`, briefly ask the contact to wait just a second while you perform it.\n"
                '\n'.join(next_action_lines)
            )

        ## 4) Set the "Reach Person" task
        self.set_task("reach_person", objective, checklist)
