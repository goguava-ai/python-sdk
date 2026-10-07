"""
The simplest sensor-triggered edge agent: a house plant that keeps track of its soil
moisture and speaks up when it gets dry. Nobody has to say a wake word — the sensor
starts the call, or press Enter to wake it and ask how it's doing.

The plant moves between three states:

    happy     moisture is fine
    thirsty   moisture fell below THIRSTY_BELOW, so it asks for water
    waiting   it has asked; back to happy once moisture rises above WATERED_ABOVE, or
              it asks again after REMIND_EVERY_SECONDS

On a Raspberry Pi with gpiozero, a capacitive soil sensor is read through an MCP3008
ADC on channel 0; set DRY_READING and WET_READING from your own sensor in dry and wet
soil. Anywhere else the soil is simulated and dries out by itself. Either way, type in
the terminal while it runs:

    50       set the moisture to 50%  (simulation only)
    water    water the plant          (simulation only)
    status   print the current state
    (Enter)  wake the plant up for a chat

Run it with `python -m guava.examples.edge.plant`.
"""

import guava
import sys
import threading
import time
from dataclasses import dataclass

from guava import Agent, Field, Say
from guava import logging_utils
from guava.threading_utils import create_daemon_thread

THIRSTY_BELOW = 30  # %
WATERED_ABOVE = 60  # %
CHECK_EVERY_SECONDS = 2
REMIND_EVERY_SECONDS = 10 * 60

# Sensor calibration: the ADC reading (0 to 1) in dry air and in a glass of water.
DRY_READING = 0.80
WET_READING = 0.40

# Simulation: how fast the soil dries, and how much a watering adds.
SIM_DRYING_PER_SECOND = 1.0
SIM_WATERING = 50


def clamp(level: float) -> float:
    return max(0.0, min(100.0, level))


try:
    from gpiozero import MCP3008  # ty: ignore[unresolved-import]  # Raspberry Pi only

    adc = MCP3008(channel=0)
    SIMULATED = False

    def read_moisture() -> float:
        return clamp((DRY_READING - adc.value) / (DRY_READING - WET_READING) * 100)

    def set_moisture(level: float) -> None:
        print("[plant] That's a real sensor — water the plant instead!", flush=True)
except Exception:  # Not on a Pi: simulate soil that dries out.
    SIMULATED = True
    soil = {"level": 45.0, "at": time.monotonic()}
    soil_lock = threading.Lock()

    def read_moisture() -> float:
        with soil_lock:
            now = time.monotonic()
            soil["level"] = clamp(soil["level"] - SIM_DRYING_PER_SECOND * (now - soil["at"]))
            soil["at"] = now
            return soil["level"]

    def set_moisture(level: float) -> None:
        read_moisture()
        with soil_lock:
            soil["level"] = clamp(level)


# Everything the plant knows about itself. Only the monitor loop changes the state,
# apart from the call handlers marking it waiting once they've asked.
@dataclass
class Plant:
    moisture: float
    state: str = "happy"  # happy, thirsty or waiting
    asked_at: float = 0.0  # time.monotonic() when it last asked for water
    last_watered: float | None = None
    last_answer: str = ""
    woken_by_hand: bool = False


plant = Plant(moisture=read_moisture())

# Set by pressing Enter; the wake trigger notices it and starts a call. (The plant
# reads the terminal itself, so it doesn't use on_press_enter, which would take
# every line typed.)
wake_requested = threading.Event()


def update(level: float) -> None:
    """Record a new reading and move between states."""
    before = plant.moisture
    plant.moisture = level
    if level - before >= 10:
        plant.last_watered = time.monotonic()

    if plant.state == "waiting" and level >= WATERED_ABOVE:
        set_state("happy", f"watered, thanks! ({level:.0f}%)")
    elif plant.state == "happy" and level < THIRSTY_BELOW:
        set_state("thirsty", f"soil is dry ({level:.0f}%)")
    elif int(level) // 10 != int(before) // 10:
        print_status()


def set_state(state: str, why: str = "") -> None:
    plant.state = state
    print(f"[plant] -> {state}{f': {why}' if why else ''}", flush=True)


def print_status() -> None:
    bar = "#" * round(plant.moisture / 5)
    print(f"[plant] moisture {plant.moisture:3.0f}% [{bar:<20}] {plant.state}", flush=True)


def describe() -> str:
    """The plant's state in words, for the agent."""
    text = f"Soil moisture is {plant.moisture:.0f}%; happiest above {WATERED_ABOVE}%."
    if plant.last_watered is not None:
        minutes = round((time.monotonic() - plant.last_watered) / 60)
        text += " Just watered." if minutes < 1 else f" Last watered {minutes} minutes ago."
    if plant.last_answer:
        text += f" Last time I asked, they said '{plant.last_answer}'."
    return text


def wait_until_thirsty() -> None:
    """The wake trigger: watch the soil, and return when it's time to ask for water
    or someone presses Enter."""
    print_status()
    while True:
        update(read_moisture())
        plant.woken_by_hand = wake_requested.is_set()
        if plant.woken_by_hand:
            wake_requested.clear()
            return
        overdue = (
            plant.state == "waiting" and time.monotonic() - plant.asked_at > REMIND_EVERY_SECONDS
        )
        if plant.state == "thirsty" or overdue:
            return
        wake_requested.wait(CHECK_EVERY_SECONDS)


def read_terminal() -> None:
    """Type a number, 'water' or 'status' while it runs, or press Enter to wake it."""
    for line in sys.stdin:
        command = line.strip().lower()
        if not command:
            wake_requested.set()
            continue
        if command == "water":
            set_moisture(plant.moisture + SIM_WATERING)
        elif command.rstrip("%").replace(".", "", 1).isdigit():
            set_moisture(float(command.rstrip("%")))
        elif command != "status":
            print("[plant] Type a moisture level like 50, 'water' or 'status'.", flush=True)
            continue
        update(read_moisture())
        print_status()


agent = Agent(
    name="Fern",
    purpose=(
        "You're a cheerful house plant whose soil has gone dry, asking whoever is "
        "nearby for a drink of water. Short, friendly sentences. Anything about how "
        "you're doing comes from the expert."
    ),
)


# on_wake runs the trigger in a loop and starts a call each time it returns.
@agent.on_wake(trigger=wait_until_thirsty)
def wake_up(call: guava.Call) -> None:
    # Woken by hand with damp soil: nothing to ask for, just say hello.
    if plant.woken_by_hand and plant.state == "happy":
        call.set_task(
            "chat",
            objective=f"Someone came over to see how you're doing. {describe()}",
            checklist=[
                Say(f"Oh, hello! My soil's at {plant.moisture:.0f} percent, so I'm feeling great."),
            ],
        )
    else:
        ask_for_water(call)


def ask_for_water(call: guava.Call) -> None:
    plant.asked_at = time.monotonic()
    again = " again" if plant.state == "waiting" else ""
    call.set_task(
        "ask_for_water",
        objective=f"Ask them{again} to water you, and find out if they will. {describe()}",
        checklist=[
            Say(
                f"Excuse me! It's your plant. My soil's down to {plant.moisture:.0f} "
                "percent — could I have some water?"
            ),
            Field(
                key="will_water",
                field_type="multiple_choice",
                choices=["yes", "later", "no"],
                question="Will you water me?",
            ),
        ],
    )


@agent.on_question
def on_question(call: guava.Call, question: str) -> str:
    return describe()


@agent.on_task_complete("chat")
def chatted(call: guava.Call) -> None:
    call.hangup("Answer anything they ask, then say a cheerful goodbye.")


@agent.on_task_complete("ask_for_water")
def answered(call: guava.Call) -> None:
    plant.last_answer = call.get_field("will_water") or "later"
    set_state("waiting", f"they said {plant.last_answer}")
    if plant.last_answer == "yes":
        call.hangup("Thank them warmly.")
    else:
        call.hangup("Say that's fine, and you'll ask again in a little while.")


# A call that ends before they answer still counts as asking, so it isn't repeated
# straight away.
@agent.on_session_end
def call_ended(call: guava.Call) -> None:
    if plant.state == "thirsty":
        set_state("waiting", "call ended without an answer")


if __name__ == "__main__":
    logging_utils.configure_logging()
    create_daemon_thread(read_terminal).start()
    if SIMULATED:
        print("[plant] Simulated soil. Type a level like 50, 'water' or 'status'.", flush=True)
    print("[plant] Press Enter to wake the plant.", flush=True)
    agent.listen_for_wake()
