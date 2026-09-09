import argparse
import guava
import logging

from guava import Agent
from guava import logging_utils
from guava.examples import get_agent_number

logger = logging.getLogger("slow_speech")

# `speech_speed` sets the TTS playback rate (time-stretch, pitch preserved) via a
# named preset: "x-slow", "slow", "medium" (normal), "fast", or "x-fast".
# Here we run the agent at the "slow" preset so speech is easier to follow.
agent = Agent(
    name="Nova",
    organization="Clearfield Home & Living",
    purpose="Answer caller questions clearly and at a relaxed pace.",
    speech_speed="slow",
)


@agent.on_question
def on_question(call: guava.Call, question: str) -> str:
    return "Thanks for asking! Let me look into that for you."


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
    group.add_argument(
        "--chat", action="store_true", help="Start a local chat session (for testing)."
    )
    group.add_argument("--sip", metavar="SIP_CODE", help="Listen on a SIP code 'guavasip-...'.")
    args = parser.parse_args()

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
