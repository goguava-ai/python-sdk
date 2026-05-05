from typing import Annotated, Literal, Union, Callable, Optional
from pydantic import StringConstraints, BaseModel, model_validator
from pydantic import Field as PydanticField
from datetime import datetime

import uuid
import warnings

E164PhoneNumber = Annotated[str, StringConstraints(pattern=r"^\+[1-9]\d{1,14}$")]

DTMFDigit = Literal["0", "1", "2", "3", "4", "5", "6", "7", "8", "9", "*", "#", "A", "B", "C", "D"]

# modality options for campaign agentic outreach
# NOTE: "rcs" is implemented (Twilio RCS sender, inbound webhook, fallback to SMS) but has not
# been tested end-to-end and is not enabled for release. To enable, add "rcs" back to this Literal.
# TODO: email, whatsapp
OutreachModality = Literal["sms"]

Language = Literal["english", "spanish", "french", "german", "italian"]

FieldTypes = Literal["text", "date", "datetime", "integer", "multiple_choice", "calendar_slot"]
ChoiceGeneratorFunction = Callable[[str], tuple[list[str], list[str]]]

class Field(BaseModel):
    item_type: Literal["field"] = 'field'

    # The key for this collection. This key can be used later with get_field() to retreive the value.
    key: str

    # Natural-language instruction to the LLM about how to collect this value.
    # Use when you do not particularly care how the agent phrases its question.
    description: str = ''

    # Encourages the agent to ask for the field in a particular way. Use instead
    # of description when you want more control over the phrasing.
    question: str = ''

    # Controls parsing and validation. "calendar_slot" and "multiple_choice"
    # require either choices or choice_generator.
    field_type: FieldTypes = 'text'

    # If False, the agent can skip this field if the caller is unwilling to provide it.
    required: bool = True

    # Static list of valid options for "calendar_slot" and "multiple_choice"
    # fields. Use when the list is small. Large lists should use choice_generator.
    choices: list[str] = PydanticField(default_factory=list)

    # Takes a query string and returns (matching, fallback) lists. Use for large
    # or dynamic option sets with "calendar_slot" and "multiple_choice".
    choice_generator: Optional[ChoiceGeneratorFunction] = None

    # Preview feature. Don't document yet.
    searchable: bool = False

    @model_validator(mode="after")
    def validate_choices(self):
        if self.field_type == 'datetime':
            raise NotImplementedError("Datetime collection is not yet implemented.")
        if self.field_type == 'calendar_slot':
            print("NOTE: For calendar_slot, choices / choice_generator must return ISO-8601 formatted datetimes: YYYY-MM-ddTHH:mm")
            if self.choices:
                # Catch any non-isoformatted initial choices
                _ = [datetime.fromisoformat(x) for x in self.choices]
        if (self.choices or self.choice_generator) and self.field_type not in ("multiple_choice", "calendar_slot"):
            raise TypeError(f"Field type {self.field_type} does not support choices attribute.")
        if len(self.choices) >= 10:
            warnings.warn("Perfomance degrades with large number of choices for multiple choice field. Use `choice_generator` instead", UserWarning)
        return self

class SerializableField(BaseModel):
    """
    Serializable verion of Field.
    Replaces the non-serializable choice_generator attribute with a boolean flag
    """
    item_type: Literal["field"] = 'field'
    key: str
    description: str = ''
    question: str = ''
    field_type: FieldTypes = 'text'
    required: bool = True
    # multiple choice
    choices: list[str] = PydanticField(default_factory=list)
    is_search_field: bool = False


class ReachPersonOutcome(BaseModel):
    """
    Defines a possible outcome when attempting to reach a contact.

    Attributes:
        key: Unique identifier for this outcome (e.g., 'contact_available', 'wrong_number')
        on_outcome: Callback function to execute when this outcome is selected
        description: Optional human-readable description of what this outcome represents
        next_action_preview: Optional preview of the next action in 2nd person, starting with
            a verb (e.g., "pull up the first question", "record their response"). This helps
            the LLM transition smoothly by saying "Let me just [next_action_preview]" instead
            of awkwardly stalling.
    """
    key: str
    on_outcome: Callable[[], None]
    description: Optional[str] = None
    next_action_preview: Optional[str] = None


class Say(BaseModel):
    item_type: Literal["say"] = 'say'
    statement: str
    key: str

    # NOTE: We override the constructor to make it 
    # easy for the client to declare a notify action item
    # via Say("blah balh...").
    # When overriding the contructure, pydantic requires
    # capturing all the initial constructors's fields, hence the **data
    # even though the only field we're interesed in is the statement field
    def __init__(self, statement, key='', **data):
        if not key:
            key = uuid.uuid4().hex[:5]
        super().__init__(statement=statement, key=key)
    
class Todo(BaseModel):
    item_type: Literal["todo"] = 'todo'
    key: str
    description: str

    def __init__(self, description, key='', **data):
        if not key:
            key = uuid.uuid4().hex[:5]
        super().__init__(description=description, key=key)

ActionItem = Annotated[
    Union[
        SerializableField,
        Say,
        Todo
    ],
    PydanticField(discriminator="item_type"),
]
