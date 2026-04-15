import logging
import os
import guava

from guava.helpers.rag import DocumentQA
from guava import logging_utils, Agent
from guava.examples.example_data import PROPERTY_INSURANCE_POLICY

logger = logging.getLogger("guava.examples.property_insurance")

agent = Agent(
    organization="Harper Valley Property Insurance",
    purpose="Answer questions regarding property insurance policy until there are no more questions",
)

document_qa = DocumentQA(documents=PROPERTY_INSURANCE_POLICY)


@agent.on_question
def on_question(call: guava.Call, question: str) -> str:
    answer = document_qa.ask(question)
    logger.info("RAG answer: %s", answer)
    return answer


if __name__ == "__main__":
    logging_utils.configure_logging()
    agent.inbound_phone(os.environ["GUAVA_AGENT_NUMBER"]).run()
