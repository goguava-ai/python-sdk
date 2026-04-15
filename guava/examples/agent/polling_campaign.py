import argparse
import os
import guava
import logging

from guava.campaigns import get_or_create_campaign, Contact
from guava import logging_utils, Agent, Field

logger = logging.getLogger("guava.examples.polling_campaign")

agent = Agent(
    name="Jordan",
    organization="Harper Valley Research Center",
    purpose="Conduct a non-partisan political opinion poll",
)


@agent.on_call_start
def on_call_start(call: guava.Call):
    first_name = call.get_variable("first_name")
    call.reach_person(
        contact_full_name=first_name,
        greeting=(
            f"Hi, is this {first_name}? I'm calling from the Harper Valley Research Center. "
            "We're conducting a brief, non-partisan poll about issues affecting your State."
        ),
    )


@agent.on_reach_person
def on_reach_person(call: guava.Call, outcome: str) -> None:
    if outcome == "unavailable":
        call.hangup()
    elif outcome == "available":
        first_name = call.get_variable("first_name")
        call.set_task(
            "political_poll",
            objective=(
                f"Conduct a brief political opinion poll with {first_name}. "
                "Be polite, non-partisan, and respect their time."
            ),
            checklist=[
                Field(
                    key="top_issue",
                    description="The most important issue to the respondent right now",
                    question="What would you say is the most important issue facing your state right now?",
                    field_type="text",
                ),
                Field(
                    key="governor_approval",
                    description="Approval rating of the current governor",
                    question="Do you approve or disapprove of the job the current governor is doing?",
                    field_type="multiple_choice",
                    choices=[
                        "approve",
                        "disapprove",
                        "no_opinion",
                    ],
                ),
                Field(
                    key="likely_to_vote",
                    description="How likely the respondent is to vote in the next election",
                    question="How likely are you to vote in the upcoming election?",
                    field_type="multiple_choice",
                    choices=["very_likely", "likely", "unlikely", "very_unlikely"],
                ),
            ],
        )


@agent.on_task_complete("political_poll")
def on_poll_complete(call: guava.Call):
    # Here is where you would read the poll results using call.get_field(...)
    call.hangup(
        "Thank them for participating and let them know the results will be published next month."
    )


if __name__ == "__main__":
    logging_utils.configure_logging()

    def parse_contact_arg(s: str) -> Contact:
        name, _, phone = s.partition(":")
        return Contact(phone_number=phone.strip(), data={"first_name": name.strip()})

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--contact",
        action="append",
        type=parse_contact_arg,
        dest="contacts",
        metavar="NAME:PHONE",
        required=True,
        help='Contact to call, e.g. "Alice:+13235550102"',
    )
    args = parser.parse_args()

    campaign = get_or_create_campaign(
        "political-poll-example-5",
        origin_phone_numbers=[os.environ["GUAVA_AGENT_NUMBER"]],
        # Calling window times are interpreted in the campaign timezone (default: America/Los_Angeles).
        calling_windows=[
            {"day": day, "start_time": "09:00", "end_time": "21:00"}
            for day in ["monday", "tuesday", "wednesday", "thursday", "friday"]
        ],
        start_date="2026-04-01",
        max_concurrency=3,
    )
    logger.info("Created campaign ID %s.", campaign.id)

    result = campaign.upload_contacts(
        args.contacts, allow_duplicates=True, accepted_terms_of_service=True
    )
    logger.info("Contact upload result: %s", result)

    agent.outbound_campaign(campaign=campaign).run()
