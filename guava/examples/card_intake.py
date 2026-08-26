"""
Simple example for credit card intake.
"""

import guava
import argparse
import logging

from guava import Agent
from guava import logging_utils
from guava.examples import get_agent_number

logger = logging.getLogger("card_intake")

agent = Agent(
    name="Grace",
    organization="Refunds LLC",
    purpose="Taking in payment card info to issue a refund.",
    voice="grace",
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
        "card_intake",
        objective="You are here to collect payment information",
        checklist=[
            guava.Field(
                key="card_number",
                field_type="credit_card_number",
                description="Should be between 13 and 19 digits",
            ),
            guava.Field(
                key="expiration_date",
                field_type="digit_sequence",
                description="should be 4 digits. E.g august 2030 would be 0830",
            ),
            guava.Field(
                key="cvv",
                field_type="cvv",
                description="3 digit security code",
            ),
        ],
    )


# This callback will be invoked when the waitlist task is finished.
@agent.on_task_complete("card_intake")
def on_card_intake_done(call: guava.Call) -> None:
    # Here is where you would save this information to your backend.
    logger.info("Successfully collected card number, expiration date, and CVV.")
    call.hangup("Thank the caller and let them know you'll process their refund. Then hangup.")


if __name__ == "__main__":
    logging_utils.configure_logging()

    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--phone", metavar="PHONE_NUMBER", nargs="?", const="", help="Listen for phone calls."
    )
    group.add_argument(
        "--webrtc", metavar="WEBRTC_CODE", nargs="?", const="", help="Listen on a WebRTC code."
    )
    group.add_argument("--local", action="store_true", help="Start a local call.")
    group.add_argument("--sip", metavar="SIP_CODE", help="Listen on a SIP code 'guavasip-...'.")
    group.add_argument("--chat", action="store_true", help="Start an interactive terminal chat.")
    args = parser.parse_args()

    # Every Agent can be attached to one of many different channels.
    if args.phone is not None:
        agent.listen_phone(args.phone or get_agent_number())
    elif args.webrtc is not None:
        agent.listen_webrtc(args.webrtc or None)
    elif args.sip:
        agent.listen_sip(args.sip)
    elif args.chat:
        agent.chat()
    else:
        agent.call_local()
