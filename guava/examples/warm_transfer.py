import argparse
import guava
import secrets
import logging

from guava import logging_utils
from guava.examples import get_agent_number


# Keep a mapping of calls so we can conference them together.
WARM_TRANSFERS: dict[str, guava.Call] = {}

logger = logging.getLogger("warm_transfer_example")


runner = guava.Runner()

agent = guava.Agent(
    name="Nova",
    organization="Acme Corp",
)


@agent.on_call_start
def on_call_start(call: guava.Call):
    call.set_task(task_id="collect_reason", checklist=[guava.Field(key="reason_for_calling")])


@agent.on_task_complete("collect_reason")
def on_collect_reason(call: guava.Call):
    call.set_task(
        "stall_customer",
        """Inform the caller that you're checking if a customer service
                    representative is ready to help them. Stay with the caller on the
                    line until the expert notifies you that the representative is ready.""",
    )

    # Generate a random conference ID that will be eventually used to join the two calls.
    conference_id = secrets.token_hex(10)

    # Keep a reference to this call object so we can trigger it from another handler.
    WARM_TRANSFERS[conference_id] = call

    # Add this new outbound call onto our existing runner.
    runner.call_phone(
        outbound_agent,
        agent_number,
        transfer_destination,
        variables={
            "conference_id": conference_id,
            "call_reason": call.get_field("reason_for_calling"),
        },
    )


outbound_agent = guava.Agent(
    name="Nova",
    organization="Acme Corp",
    purpose="You are an outbound calling agent. You talk to customer service representatives on behalf of callers and brief them before a warm transfer.",
)


@outbound_agent.on_call_start
def on_outbound_call_start(call: guava.Call):
    call.set_task(
        "confirm_ready",
        f"""A caller is calling about {call.get_variable("call_reason")}. You are not talking to the caller - you are talking to a customers service representative.""",
        checklist=[
            "Inform the customer service agent of the caller's reason for calling.",
            "Determine if the service agent is ready for a transfer.",
        ],
    )


@outbound_agent.on_task_complete("confirm_ready")
def on_confirm_ready(call: guava.Call):
    # Look up the conference ID.
    conference_id = call.get_variable("conference_id")
    other_call = WARM_TRANSFERS[conference_id]

    # Join the two calls.
    destination = f"conference:{conference_id}"
    other_call.transfer(destination, "The customer service representative is ready.")
    call.transfer(
        destination, "Transfer to the caller. Tell the rep that you are 'Patching in the caller.'"
    )

    # Remove the old call ID.
    del WARM_TRANSFERS[conference_id]


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "transfer_destination", metavar="PHONE_NUMBER", help="Number to warm transfer callers to."
    )
    parser.add_argument(
        "--agent-number",
        metavar="PHONE_NUMBER",
        help="Number to listen on. Defaults to GUAVA_AGENT_NUMBER or your account's number.",
    )
    args = parser.parse_args()

    transfer_destination: str = args.transfer_destination
    agent_number: str = args.agent_number or get_agent_number()

    logging_utils.configure_logging()
    runner.listen_phone(agent, agent_number).run()
