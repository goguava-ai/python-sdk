"""
Barebones information-extraction benchmark bot.

Collects a full set of personal and payment fields in a single task, asking for
each field exactly one at a time, then hangs up.
"""

import csv
import guava
import logging
import re
from collections import defaultdict

from guava import Agent
from guava import logging_utils
from guava.events import AgentSpeechEvent, CallerSpeechEvent
from guava.examples import get_agent_number

logger = logging.getLogger("info_extraction")

# Accumulated transcript per call id: list of (speaker, utterance_id, text).
# utterance_id lets us collapse streaming caller partials into a single line.
_transcripts: dict[str, list[list[str | None]]] = defaultdict(list)

# Fields collected in the order they are asked.
FIELD_KEYS = [
    "first_name",
    "last_name",
    "dob",
    "state",
    "zip_code",
    "email",
    "household_size",
    "phone_number",
    "credit_card_number",
    "expiration_date",
]

# Fields whose values should be reduced to digits 0-9 only.
DIGIT_FIELDS = {
    "zip_code",
    "phone_number",
    "credit_card_number",
    "household_size",
    "expiration_date",
}

agent = Agent(
    name="Grace",
    organization="",
    purpose="",
    voice="grace",
)


@agent.on_call_start
def on_call_start(call: guava.Call) -> None:
    call.set_task(
        "info_extraction",
        objective=(
            "You are here to collect the caller's information. Ask for exactly one "
            "field at a time and wait for the caller's answer before asking for the "
            "next one. Never ask for more than one field in a single turn. Additionally, never confirm or read back anything. "
            "Once the caller provides one field, move on to the next one."
        ),
        checklist=[
            guava.Field(
                key="first_name",
                field_type="text",
                question="What is your first name?",
                description="This is a name, if they provide it by spelling, use the spelled value."
            ),
            guava.Field(
                key="last_name",
                field_type="text",
                question="What is your last name?",
            ),
            guava.Field(
                key="dob",
                field_type="date",
                question="What is your date of birth?",
            ),
            guava.Field(
                key="state",
                field_type="text",
                question="What state do you live in?",
            ),
            guava.Field(
                key="zip_code",
                field_type="digit_sequence",
                question="What is your zip code?",
            ),
            guava.Field(
                key="email",
                field_type="text",
                question="What is your email address?",
            ),
            guava.Field(
                key="household_size",
                field_type="integer",
                question="How many people are in your household?",
            ),
            guava.Field(
                key="phone_number",
                field_type="digit_sequence",
                question="What is your phone number?",
            ),
            guava.Field(
                key="credit_card_number",
                field_type="digit_sequence",
                question="What is your credit card number?",
            ),
            guava.Field(
                key="expiration_date",
                field_type="digit_sequence",
                question="What is your card's expiration date?",
            ),
        ],
    )


@agent.on_caller_speech
def on_caller_speech(call: guava.Call, event: CallerSpeechEvent) -> None:
    entries = _transcripts[call.id]
    # Streaming partials reuse utterance_id; update the line in place if we've
    # already recorded it, otherwise append a new one.
    for entry in entries:
        if event.utterance_id is not None and entry[1] == event.utterance_id:
            entry[2] = event.utterance
            return
    entries.append(["caller", event.utterance_id, event.utterance])


@agent.on_agent_speech
def on_agent_speech(call: guava.Call, event: AgentSpeechEvent) -> None:
    _transcripts[call.id].append(["agent", None, event.utterance])


@agent.on_task_complete("info_extraction")
def on_info_extraction_done(call: guava.Call) -> None:
    logger.info("Successfully collected all caller information.")
    call.hangup("Thank the caller and let them know they're all set. Then hangup.")


@agent.on_session_end
def on_session_end(call: guava.Call) -> None:
    # Name the file after the caller so concurrent calls don't overwrite it.
    caller = getattr(call.call_info, "from_number", None) or getattr(call.call_info, "from_aor", "")
    digits = re.sub(r"\D", "", str(caller).split("@")[0]) or call.id

    # Write the transcript file
    entries = _transcripts.pop(call.id, [])
    with open(f"transcript_{digits}.txt", "w") as f:
        f.write(f"call_id {call.id}\n")
        f.writelines(f"[{speaker}]: {text}\n" for speaker, _utterance_id, text in entries)

    path = f"info_extraction_{digits}.csv"
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["field", "value"])
        for key in FIELD_KEYS:
            value = call.get_field(key) or ""
            if key == 'dob' and value:
                value = f"{value['year']}-{value['month']}-{value['day']}"
            value = str(value)
            if key in DIGIT_FIELDS:
                value = re.sub(r"\D", "", value)
            writer.writerow([key, value])
    logger.info("Wrote collected information to %s", path)


if __name__ == "__main__":
    logging_utils.configure_logging()
    agent.listen_phone(get_agent_number())
