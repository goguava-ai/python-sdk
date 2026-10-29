from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class PaginatedResponse(BaseModel, Generic[T]):
    """A page of results from a paginated Guava REST endpoint."""

    results: list[T] = Field(description="Results on this page.")
    next_url: str | None = Field(
        default=None,
        description="URL of the next page of results, or null if this is the last page. Send a GET request to it as-is.",
    )

    # Name schemas e.g. SMSMessagePage, rather than PaginatedResponse_SMSMessage_.
    @classmethod
    def model_parametrized_name(cls, params: tuple[type[Any], ...]) -> str:
        return f"{params[0].__name__}Page"
