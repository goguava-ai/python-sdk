import logging
import guava
import argparse

from guava.helpers.rag import DocumentQA
from guava import logging_utils, Agent
from guava.examples.example_data import PROPERTY_INSURANCE_POLICY
from guava.examples import example_data

logger = logging.getLogger("guava.examples.property_insurance")

agent = Agent(
    organization="Harper Valley Property Insurance",
    purpose="Answer questions regarding property insurance policy until there are no more questions",
)

# This is a built-in knowledge base helper that we will use for this example.
# You can use any RAG system you prefer.
document_qa = DocumentQA(documents=PROPERTY_INSURANCE_POLICY)


# When the Agent is asked a question that it cannot answer, it will invoke the on_question callback.
@agent.on_question
def on_question(call: guava.Call, question: str) -> str:
    # Forward the Agent's question to the knowledge base and return the answer.
    # You can plug in any knowledge base system you want here.
    answer = document_qa.ask(question)
    logger.info("RAG answer: %s", answer)
    return answer


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
    args = parser.parse_args()

    # Every Agent can be attached to one of many different channels.
    if args.phone is not None:
        agent.listen_phone(args.phone or example_data.get_phone_number())
    elif args.webrtc is not None:
        agent.listen_webrtc(args.webrtc or None)
    elif args.sip:
        agent.listen_sip(args.sip)
    else:
        agent.call_local()
