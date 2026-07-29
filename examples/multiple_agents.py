"""
This example shows you how to serve muliple agents in one process using guava.Runner
"""

from guava import logging_utils, Agent, Runner
from guava.examples import get_agent_number

agent_a = Agent(
    name="Grace",
    purpose="You are a helpful voice agent.",
)

agent_b = Agent(
    name="Jordan",
    purpose="You are a helpful voice agent.",
)

if __name__ == "__main__":
    logging_utils.configure_logging()

    # You can use guava.Runner to serve multiple agents, each attached
    # to any number of channels.
    runner = Runner()
    runner.listen_phone(agent_a, get_agent_number())
    runner.listen_webrtc(agent_b)
    runner.run()
