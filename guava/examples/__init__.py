import sys
from guava import Client
import termios
import tty
import os


def terminal_picker(options: list[str], prompt: str = "Select an option") -> str:
    """Interactive arrow-key picker. Returns the selected option."""
    assert options, "options must be non-empty"
    assert sys.stdin.isatty() and sys.stdout.isatty(), "Both stdin and stdout should be ttys."

    selected = 0
    old_settings = termios.tcgetattr(sys.stdin.fileno())
    rendered_lines = 0

    def render() -> None:
        nonlocal rendered_lines

        lines = [prompt + ":"]
        for i, option in enumerate(options):
            cursor = "❯" if i == selected else " "
            lines.append(f"{cursor} {option}")

        # Move back to the first line of the previous picker render.
        if rendered_lines:
            sys.stdout.write(f"\033[{rendered_lines}F")

        # Clear and rewrite exactly the picker lines, no full-screen clearing.
        for line in lines:
            sys.stdout.write("\r\033[2K")  # Clear current line only.
            sys.stdout.write(line)
            sys.stdout.write("\n")

        # If the new render has fewer lines than before, clear leftovers.
        for _ in range(rendered_lines - len(lines)):
            sys.stdout.write("\r\033[2K\n")

        rendered_lines = len(lines)
        sys.stdout.flush()

    try:
        tty.setcbreak(sys.stdin.fileno())
        sys.stdout.write("\033[?25l")  # Hide cursor.
        render()

        while True:
            ch = sys.stdin.read(1)

            if ch in ("\r", "\n"):
                # Move to a clean line below the picker.
                sys.stdout.write("\r\033[2K")
                sys.stdout.write(f"Selected: {options[selected]}\n")
                sys.stdout.flush()
                return options[selected]

            if ch == "\x03":  # Ctrl-C
                raise KeyboardInterrupt

            if ch == "\x1b":
                seq = sys.stdin.read(2)

                if seq == "[A":  # Up arrow
                    selected = (selected - 1) % len(options)
                    render()
                elif seq == "[B":  # Down arrow
                    selected = (selected + 1) % len(options)
                    render()

    finally:
        termios.tcsetattr(sys.stdin.fileno(), termios.TCSADRAIN, old_settings)
        sys.stdout.write("\033[?25h")  # Show cursor.
        sys.stdout.flush()


def get_agent_number() -> str:
    """
    For use in Guava examples. Returns the agent's phone number from the GUAVA_AGENT_NUMBER environment variable,
    or from the user's account if not set. Prints an error message and exits if no number is found.
    """

    if "GUAVA_AGENT_NUMBER" in os.environ:
        return os.environ["GUAVA_AGENT_NUMBER"]

    client = Client()
    numbers = client.list_numbers()
    if len(numbers) == 0:
        print("No phone numbers found. Please purchase a number first.")
        exit(1)
    elif len(numbers) == 1:
        return numbers[0].phone_number
    elif sys.stdin.isatty() and sys.stdout.isatty():
        return terminal_picker(
            [n.phone_number for n in numbers],
            prompt="Multiple phone numbers found. Select one",
        )
    else:
        print(
            f"Multiple phone numbers found in current org: {[n.phone_number for n in numbers]}. Please specify one with --phone."
        )
        exit(1)
