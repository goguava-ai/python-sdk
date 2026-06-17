import secrets

from guava.call import Call
from guava.types.call_info import PSTNCallInfo, CallInfo
from typing import Any
from guava.commands import (
    Command,
)


class MockCall(Call):
    def __init__(
        self,
        session_id: str | None = None,
        call_info: CallInfo = PSTNCallInfo(from_number="+15555555555", to_number="+15555555555"),
    ) -> None:
        self._session_id = session_id or "mock-" + secrets.token_hex(6)
        self._call_info = call_info

        self._command_queue: list[Command] = []
        self._field_values: dict[str, Any] = {}
        self._variables: dict[str, Any] = {}

    def set_field(self, field_name: str, field_value: Any) -> None:
        """Set a field value on the mock call.

        Args:
            field_name: The field key to set.
            field_value: The value to assign to the field.
        """
        self._field_values[field_name] = field_value

    def send_command(self, command: Command):
        self._command_queue.append(command)
