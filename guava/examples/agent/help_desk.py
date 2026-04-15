import os
import guava
import logging

from guava import Agent, SuggestedAction
from guava import logging_utils
from guava.examples.example_data import FURNITURE_RETAILER_QA
from guava.helpers.rag import DocumentQA
from guava.helpers.openai import IntentRecognizer

logger = logging.getLogger("help_desk")

agent = Agent(
    name="Nova",
    organization="Clearfield Home & Living",
    purpose="Answer questions and route callers to the appropriate department.",
)

document_qa = DocumentQA(documents=FURNITURE_RETAILER_QA)

intent_recognizer = IntentRecognizer(
    {
        "sales": "New purchases, product availability, pricing, promotions, price matching, store hours, order status, order changes and cancellations",
        "delivery-and-returns": "Delivery scheduling and rescheduling, installation, assembly, damaged-on-arrival items, returns, exchanges, refund status, warranty claims and repairs",
        "account-management": "Charges, invoices, payment plans, financing, billing disputes, rewards points, membership accounts, bulk and business orders",
        "other": "Anything else not listed under another category.",
    }
)


@agent.on_question
def on_question(call: guava.Call, question: str) -> str:
    answer = document_qa.ask(question)
    logger.info("RAG answer: %s", answer)
    return answer


@agent.on_action_requested
def on_action_requested(call: guava.Call, request: str) -> SuggestedAction:
    return SuggestedAction(key=intent_recognizer.classify(request))


@agent.on_action("sales")
def sales(call: guava.Call):
    call.transfer(
        "+15555555555",
        "Notify the caller that you will be transferring them to the Sales department.",
    )


@agent.on_action("delivery-and-returns")
def delivery_returns(call: guava.Call):
    call.transfer(
        "+15555555555",
        "Notify the caller that you will be transferring them to the Delivery and Returns department.",
    )


@agent.on_action("account-management")
def account_management(call: guava.Call):
    call.transfer(
        "+15555555555",
        "Notify the caller that you will be transferring them to the Account Management department.",
    )


@agent.on_action("other")
def other_request(call: guava.Call):
    call.transfer(
        "+15555555555",
        "Notify the caller that you will be connecting them with a service representative.",
    )


if __name__ == "__main__":
    logging_utils.configure_logging()
    agent.inbound_phone(os.environ["GUAVA_AGENT_NUMBER"]).run()
