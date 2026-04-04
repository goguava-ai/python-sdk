"""
Political opinion polling example.

Demonstrates how to create a campaign, upload contacts, define a
CallController, and serve calls with structured data collection.

Usage:
    export GUAVA_API_KEY="your-api-key"
    export GUAVA_BASE_URL="https://guava.gridspace.com/"
    uv run python -m guava.examples.polling
"""

import os

import guava
from guava import Field, Say
from guava.outbound_campaigns import get_or_create_campaign


# -- Campaign setup ----------------------------------------------------------

CAMPAIGN_NAME = "political-poll-example"
ORIGIN_PHONE_NUMBER = os.environ["GUAVA_AGENT_NUMBER"]

contacts = [
    {"phone_number": "+13235550102", "data": {"first_name": "Alice", "district": "District 5"}},
    {"phone_number": "+13235550103", "data": {"first_name": "Bob", "district": "District 12"}},
    {"phone_number": "+13235550104", "data": {"first_name": "Carol", "district": "District 5"}},
]


# -- Controller --------------------------------------------------------------


class PollController(guava.CallController):
    def __init__(self, data=None):
        data = data or {}
        self.first_name = data.get("first_name", "there")
        self.district = data.get("district", "your area")

        self.set_persona(
            organization_name="National Opinion Research Center",
            agent_name="Jordan",
            agent_purpose="conduct a non-partisan political opinion poll",
        )
        self.set_task(
            objective=(
                f"Conduct a brief political opinion poll with {self.first_name} in {self.district}. "
                "Be polite, non-partisan, and respect their time. "
                "If they decline to answer any question, mark it as 'declined' and move on."
            ),
            checklist=[
                Say(
                    f"Hi, is this {self.first_name}? I'm calling from the National Opinion Research Center. "
                    f"We're conducting a brief, non-partisan poll about issues affecting {self.district}. "
                    "It should only take about two minutes — would you be willing to participate?"
                ),
                Field(
                    key="willing_to_participate",
                    description="Whether the respondent agrees to take the poll",
                    field_type="multiple_choice",
                    choices=["yes", "no"],
                ),
                "If they said no, thank them for their time and end the call.",
                Field(
                    key="top_issue",
                    description="The most important issue to the respondent right now",
                    question=f"What would you say is the most important issue facing {self.district} right now?",
                    field_type="multiple_choice",
                    choices=[
                        "economy",
                        "healthcare",
                        "education",
                        "housing",
                        "public_safety",
                        "environment",
                        "other",
                    ],
                ),
                Field(
                    key="governor_approval",
                    description="Approval rating of the current governor",
                    question="Do you approve or disapprove of the job the current governor is doing?",
                    field_type="multiple_choice",
                    choices=[
                        "strongly_approve",
                        "approve",
                        "disapprove",
                        "strongly_disapprove",
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
                Field(
                    key="additional_comments",
                    description="Any additional thoughts the respondent wants to share",
                    question="Is there anything else you'd like us to know about the issues affecting your community?",
                    field_type="text",
                    required=False,
                ),
            ],
            on_complete=self._save_results,
        )

    def _save_results(self):
        print(f"\n--- Poll result for {self.first_name} ({self.district}) ---")
        for key, value in self._field_values.items():
            print(f"  {key}: {value}")
        print()
        self.send_instruction(
            "Thank them for participating and let them know the results will be published next month. End the call."
        )


# -- Main --------------------------------------------------------------------

campaign = get_or_create_campaign(
    CAMPAIGN_NAME,
    origin_phone_numbers=[ORIGIN_PHONE_NUMBER],
    # Calling window times are interpreted in the campaign timezone (default: America/Los_Angeles).
    calling_windows=[
        {"day": day, "start_time": "09:00", "end_time": "21:00"}
        for day in ["monday", "tuesday", "wednesday", "thursday", "friday"]
    ],
    start_date="2026-04-01",
    max_concurrency=3,
)
print("Campaign:", campaign)

result = campaign.upload_contacts(contacts, allow_duplicates=True, accepted_terms_of_service=True)
print("Upload:", result)

client = guava.Client()
client.serve_campaign(campaign=campaign, controller=PollController)
