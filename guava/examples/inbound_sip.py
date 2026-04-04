import argparse

from guava.examples.thai_palace import ThaiPalaceCallController
from guava import logging_utils

import guava

if __name__ == "__main__":
    logging_utils.configure_logging()

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "sip_code", nargs="?", default=None, type=str, help="The SIP code of the agent."
    )
    args = parser.parse_args()

    client = guava.Client()
    client.listen_inbound(
        sip_code=args.sip_code or client.create_sip_agent(),
        controller_class=ThaiPalaceCallController,
    )
