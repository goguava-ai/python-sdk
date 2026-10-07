"""
The simplest edge order-taker: a barista that asks for a drink, a size and a name, then
reads the order back with a price worked out in code.

Run it with `python -m guava.examples.edge.barista`, then say "hey guava" or
press Enter.
"""

import guava

from guava import Agent, Field, Say
from guava import logging_utils
from guava.events import AgentSpeechEvent

# Prices are for a medium. The agent never quotes a price; the till works it out.
MENU = {"drip coffee": 2.50, "latte": 4.25, "cappuccino": 4.25, "mocha": 4.75, "tea": 2.75}
SIZES = {"small": -0.50, "medium": 0.00, "large": 0.75}

agent = Agent(
    name="Grace",
    organization="Guava Coffee",
    purpose=(
        "You're the barista at Guava Coffee. Be warm and brief, a few words at a time. "
        f"We only serve {', '.join(MENU)} — if they ask for anything else, say we "
        "don't have it and name a couple of things we do. Don't quote prices."
    ),
)


# Multiple-choice fields keep the answers to things the code understands: the agent
# can only fill them with one of the choices.
@agent.on_wakeword
@agent.on_press_enter
def take_order(call: guava.Call) -> None:
    order["checked_out"] = False
    call.set_task(
        "order",
        objective=(
            "Take one drink order. Don't read the order back, total it up or say "
            "goodbye — the till checks them out."
        ),
        checklist=[
            Say("Hi! What can I get you?"),
            Field(
                key="drink",
                field_type="multiple_choice",
                choices=list(MENU),
                question="What would you like?",
            ),
            Field(
                key="size",
                field_type="multiple_choice",
                choices=list(SIZES),
                description=(
                    "Small is 12 ounces, medium 16 and large 20. Tall means "
                    "small, grande medium and venti large."
                ),
                question="What size?",
            ),
            Field(
                key="customer_name",
                field_type="text",
                description="The customer's first name for the cup, never the drink.",
                question="And a name for the cup?",
            ),
        ],
        completion_criteria="Complete as soon as you have the drink, the size and a name.",
    )


# Only one call is live at a time, so one flag is enough.
order = {"checked_out": False}


@agent.on_task_complete("order")
def order_done(call: guava.Call) -> None:
    checkout(call)


# Checkout doesn't wait on the task alone: as soon as the agent speaks with all three
# answers in hand, the till rings it up.
@agent.on_agent_speech
def check_order(call: guava.Call, event: AgentSpeechEvent) -> None:
    if all(call.get_field(k) for k in ("drink", "size", "customer_name")):
        checkout(call)


@agent.on_session_end
def call_ended(call: guava.Call) -> None:
    if not order["checked_out"] and call.get_field("drink"):
        print_receipt(call, note="call ended before checkout")


def checkout(call: guava.Call) -> None:
    if order["checked_out"]:
        return
    order["checked_out"] = True
    size, drink, name, price = print_receipt(call)
    # read_script says this word for word, so the customer hears the real price.
    dollars, cents = divmod(round(price * 100), 100)
    spoken = f"{dollars} dollars" + (f" {cents}" if cents else "")
    for_name = f" for {name}" if name else ""
    call.read_script(f"Great, that's a {size} {drink}{for_name}. That'll be {spoken}.")
    call.hangup("Say a quick, friendly thanks.")


def print_receipt(call: guava.Call, note: str = "") -> tuple[str, str, str, float]:
    drink = call.get_field("drink") or "drip coffee"
    size = call.get_field("size") or "medium"
    name = call.get_field("customer_name") or ""
    price = MENU.get(drink, 2.50) + SIZES.get(size, 0.0)
    print("\n+------------ GUAVA COFFEE ------------+", flush=True)
    print(f"| {(name or 'guest').upper():<36} |", flush=True)
    print(f"| {size + ' ' + drink:<26}{f'${price:.2f}':>10} |", flush=True)
    if note:
        print(f"| ({note}){'':<{34 - len(note)}} |", flush=True)
    print("+--------------------------------------+\n", flush=True)
    return size, drink, name, price


if __name__ == "__main__":
    logging_utils.configure_logging()
    agent.listen_for_wake()
