import guava
import logging
import os

from guava.helpers.openai import IntentRecognizer
from guava import Field, Agent, logging_utils, SuggestedAction
from dataclasses import dataclass
from datetime import date
from difflib import SequenceMatcher

logger = logging.getLogger("cash_advance")

agent = Agent(
    name="Grace",
    organization="Gridspace Credit",
)
TASKS = {"cash advance": "for cash advance requests", "other": "any other inquiries"}
intent_recognizer = IntentRecognizer(list(TASKS.keys()))
account = None


@agent.on_call_received
def on_call_received(call_info: guava.CallInfo) -> guava.IncomingCallAction:
    return guava.AcceptCall()


@agent.on_call_start
def on_call_start(call: guava.Call) -> None:
    call.set_task("intro", "Greet callers and figure out why they are calling.")


@agent.on_action_request
def on_action_request(call: guava.Call, request: str):
    choice = intent_recognizer.classify(request)
    if not choice:
        return None
    return SuggestedAction(key=choice, description=TASKS[choice])


@agent.on_action
def on_action(call: guava.Call, action_key: str):
    if action_key == "other":
        return "I'm sorry I can't help you with that."
    else:  # cash advance
        call.set_task(
            "get_account_details",
            "Gather information so we can find the caller's account.",
            checklist=[
                Field(
                    key="caller_name",
                    description="The caller's name.",
                    field_type="text",
                ),
                Field(
                    key="caller_dob",
                    description="The caller's date of birth.",
                    field_type="date",
                ),
                Field(
                    key="last_four_ssn",
                    description="The last four digits of the caller's SSN.",
                    field_type="integer",
                ),
            ],
            completion_criteria="""
Once all three piece of information are gathered, mark the task as complete.
Note that you need to mark it as complete as soon as you receive the information,
so that I can verify if the information is correct.
""",
        )


@agent.on_task_complete("get_account_details")
def try_find_customer(call: guava.Call):
    global account
    account = find_customer(
        name=call.get_field("caller_name"),
        dob=field_to_date(call.get_field("caller_dob")),
        last_four_ssn=call.get_field("last_four_ssn"),
    )

    if account is None:
        error = (
            "We couldn't find the customer's account. Ask them to double-check their information."
        )
        call.retry_task(reason=error)

    elif not account.is_active:
        call.hangup(
            "Inform the caller that their account is marked as not active and they can no longer proceed."
        )

    else:
        check_cash_advance(call)


def check_cash_advance(call: guava.Call):
    global account
    assert account

    # Actually check the advance here.
    call.set_task(
        "notify_cash_advance", "Inform the customer that they are not eligible for an advance."
    )


@dataclass
class CustomerAccount:
    name: str
    dob: date
    last_four_ssn: int
    is_active: bool


CUSTOMER_DATABASE = [
    CustomerAccount(name="John Smith", dob=date(1990, 1, 1), last_four_ssn=2521, is_active=True)
]


def find_customer(name: str, dob: date, last_four_ssn: int) -> CustomerAccount | None:
    """Just a mockup of a fuzzy search that allows some errors."""
    name_matches = [
        c for c in CUSTOMER_DATABASE if SequenceMatcher(None, name, c.name).ratio() > 0.8
    ]
    dob_matches = [c for c in name_matches if c.dob == dob]
    matches = [c for c in dob_matches if c.last_four_ssn == last_four_ssn]
    if len(matches) != 1:
        return None
    else:
        return matches[0]


def field_to_date(field: dict[str, int]) -> date:
    return date(field["year"], field["month"], field["day"])


if __name__ == "__main__":
    logging_utils.configure_logging()
    agent.listen_phone(os.environ["GUAVA_AGENT_NUMBER"])
