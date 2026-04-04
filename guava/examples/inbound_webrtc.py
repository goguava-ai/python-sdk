import argparse

from guava.examples.thai_palace import ThaiPalaceCallController
from guava import logging_utils
from datetime import timedelta
import guava

if __name__ == "__main__":
    logging_utils.configure_logging()

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "webrtc_code",
        nargs="?",
        default=None,
        type=str,
        help="The WebRTC code of the agent.",
    )
    args = parser.parse_args()

    client = guava.Client()
    client.listen_inbound(
        webrtc_code=args.webrtc_code or client.create_webrtc_agent(ttl=timedelta(minutes=5)),
        controller_class=ThaiPalaceCallController,
    )
