"""
This example attaches a political polling agent to an ongoing Guava campaign.

To use this, first create a campaign from the dashboard or CLI and add contacts.
Then, run this script with the campaign ID and the Agent will start making calls to
those registered contacts.
"""

import argparse
import guava
import logging
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
    if outcome == "available":
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
    else:
        call.hangup("Appropriately end the call.")


@agent.on_task_complete("political_poll")
def on_poll_complete(call: guava.Call):
    # Here is where you would read the poll results using call.get_field(...)
    call.hangup(
        "Thank them for participating and let them know the results will be published next month."
    )


if __name__ == "__main__":
    logging_utils.configure_logging()
    parser = argparse.ArgumentParser(
        description="Attach an example political polling agent to a campaign."
    )
    parser.add_argument(
        "campaign_code",
        help="The campaign code to attach to (e.g. gcp-...). Use the CLI or dashboard to create a campaign.",
    )
    args = parser.parse_args()

    agent.attach_campaign(args.campaign_code)
