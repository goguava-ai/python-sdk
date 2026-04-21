"""
This is a simple restaurant waitlist example that shows you how to collect information
from inbound callers through the use of `call.set_task(...)`
"""

import os
import guava
import argparse
import logging

from guava import Agent
from guava import logging_utils

logger = logging.getLogger("thai_palace")

agent = Agent(
    name="Mia",
    organization="Thai Palace",
    purpose="Helping callers join the restaurant waitlist",
)


@agent.on_call_received
def on_call_received(call_info: guava.CallInfo) -> guava.IncomingCallAction:
    # In this callback you have the option to accept or reject a call based off the caller info.
    # For now we will accept all calls. If this callback is not provided, the default behavior is
    # to accept all calls.
    return guava.AcceptCall()


@agent.on_call_start
def on_call_start(call: guava.Call) -> None:
    call.set_task(
        "waitlist",
        objective="You are a virtual assistant for Thai Palace. Add callers to the waitlist.",
        checklist=[
            guava.Field(key="caller_name", field_type="text", description="Name for the waitlist"),
            guava.Field(key="party_size", field_type="integer", description="Number of people"),
            guava.Field(
                key="phone_number",
                field_type="text",
                description="Phone number to text when the table is ready",
            ),
            "Read the phone number back to the caller to confirm.",
        ],
    )


# This callback will be invoked when the waitlist task is finished.
@agent.on_task_complete("waitlist")
def on_waitlist_done(call: guava.Call) -> None:
    # Here is where you would save this information to your backend. For now, we'll just log it.
    logger.info(
        "Added %s, party of %d, to waitlist.",
        call.get_field("caller_name"),
        call.get_field("party_size"),
    )
    call.hangup("Thank the caller and let them know we'll text when their table is ready.")


if __name__ == "__main__":
    logging_utils.configure_logging()

    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--phone", action="store_true", help="Listen for phone calls.")
    group.add_argument("--webrtc", action="store_true", help="Create on a WebRTC code.")
    group.add_argument("--local", action="store_true", help="Start a local call.")
    args = parser.parse_args()

    if args.phone:
        agent.listen_phone(os.environ["GUAVA_AGENT_NUMBER"])
    elif args.webrtc:
        agent.listen_webrtc()
    else:
        agent.call_local()
