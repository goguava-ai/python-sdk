import logging
import os
import argparse
import guava

from guava import logging_utils, Agent
from guava.examples.mock_appointments import MOCK_APPOINTMENTS
from guava.helpers.openai import DatetimeFilter

logger = logging.getLogger("guava.examples.property_insurance")

agent = Agent(
    organization="Bright Smile Dental",
    purpose="Call patients to help them scehdule a dental appointment.",
)
datetime_filter = DatetimeFilter(source_list=MOCK_APPOINTMENTS)


@agent.on_call_start
def on_call_start(call: guava.Call):
    call.reach_person(
        contact_full_name=call.get_variable("patient_name"),
    )


@agent.on_reach_person
def on_reach_person(call: guava.Call, outcome: str) -> None:
    if outcome == "unavailable":
        call.hangup("Apologize for your mistake and hang up the call.")
    elif outcome == "available":
        call.set_task(
            "schedule_appointment",
            checklist=[
                "Tell them that it's been a while since their regular cleaning with Dr. Teeth.",
                guava.Field(
                    key="appointment_time",
                    field_type="calendar_slot",
                    description="Find a time that works for the caller",
                    searchable=True,
                ),
                "Tell them their appointment has been confirmed and answer any questions before ending the call.",
            ],
        )


@agent.on_search_query("appointment_time")
def search_appointments(call: guava.Call, query: str):
    return datetime_filter.filter(query, max_results=3)


@agent.on_task_complete("schedule_appointment")
def on_appointment_scheduled(call: guava.Call):
    call.hangup("Thank them for their time and hang up the call.")


if __name__ == "__main__":
    logging_utils.configure_logging()

    parser = argparse.ArgumentParser()
    parser.add_argument("phone", type=str, help="Phone number to call.")
    parser.add_argument("name", nargs="?", help="Name of the patient", default="Benjamin Buttons")
    args = parser.parse_args()

    agent.outbound_phone(
        from_number=os.environ["GUAVA_AGENT_NUMBER"],
        to_number=args.phone,
        variables={"patient_name": args.name},
    ).run()
