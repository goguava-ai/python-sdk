# Doesn't have to be its own file
import httpx
from guava.types import OutreachModality, E164PhoneNumber
from typing import Optional, Any
from guava.client import Client
from pydantic import BaseModel, Field

import logging

from guava.telemetry import telemetry_client
from guava.utils import check_response

logger = logging.getLogger(__name__)


class Contact(BaseModel):
    phone_number: E164PhoneNumber
    data: dict[str, Any] = Field(default_factory=dict)
    outreach_modalities: Optional[list[OutreachModality]] = None


class CampaignStatus(BaseModel):
    """Status of a campaign.

    Attributes:
        status_counts: Mapping of contact status (e.g. ``"trying"``,
            ``"failed"``, ``"completed"``, ``"partially_completed"``,
            ``"do_not_call"``) to the number of contacts in that status. Only
            statuses with at least one contact are included.
    """

    status_counts: dict[str, int] = Field(default_factory=dict)


class UploadContactsResult(BaseModel):
    """Result of uploading contacts to a campaign.

    Attributes:
        created: The number of contacts that were inserted.
    """

    created: int


class DeleteContactsResult(BaseModel):
    """Result of deleting contacts from a campaign.

    Attributes:
        deleted: The number of contacts that were removed.
    """

    deleted: int


@telemetry_client.track_class()
class Campaign:
    def __init__(self, client: Client, id: str, code: str, name: str):
        self._client = client
        self._id = id
        self._code = code
        # Snapshot of the name at the time this handle was fetched. Used for
        # display/logging only; identity is keyed off id/code, never name.
        self._name = name

    @property
    def id(self) -> str:
        return self._id

    @property
    def code(self) -> str:
        return self._code

    @property
    def name(self) -> str:
        return self._name

    def upload_contacts(
        self,
        contacts: list[Contact],
        allow_duplicates: bool = False,
        accepted_terms_of_service: bool = False,
        outreach_modalities: list[OutreachModality] | None = None,
    ) -> UploadContactsResult:
        if outreach_modalities:
            for contact in contacts:
                contact.outreach_modalities = contact.outreach_modalities or outreach_modalities

        response = check_response(
            httpx.post(
                self._client.get_http_url(f"v2/campaigns/{self._code}/contacts"),
                params={
                    "allow_duplicates": str(allow_duplicates).lower(),
                    "accepted_terms_of_service": str(accepted_terms_of_service).lower(),
                },
                json={"contacts": [c.model_dump() for c in contacts]},
                headers=self._client._get_headers(),
            )
        )

        return UploadContactsResult.model_validate(response.json())

    def delete_contacts(self, phone_number: str) -> DeleteContactsResult:
        """Permanently remove every contact in this campaign with the given phone number.

        Args:
            phone_number: The contact's number. US numbers only, with or without
                the ``+1`` (e.g. ``"2125551234"`` or ``"(212) 555-1234"``); it is
                normalized to E.164 before matching.

        Returns:
            The number of contacts removed. This can be more than 1 if the number
            was uploaded more than once with ``allow_duplicates``.

        Raises:
            httpx.HTTPStatusError: If no contact matches, or one is currently mid-call.
        """
        response = check_response(
            httpx.delete(
                self._client.get_http_url(f"v2/campaigns/{self._code}/contacts"),
                params={"phone_number": phone_number},
                headers=self._client._get_headers(),
            )
        )
        return DeleteContactsResult.model_validate(response.json())

    def get_status(self) -> CampaignStatus:
        response = httpx.get(
            self._client.get_http_url(f"v2/campaigns/{self._code}/status"),
            headers=self._client._get_headers(),
        )
        check_response(response)
        return CampaignStatus.model_validate(response.json())

    def delete(self) -> None:
        response = httpx.delete(
            self._client.get_http_url(f"v2/campaigns/{self._code}"),
            headers=self._client._get_headers(),
        )
        check_response(response)

    def __repr__(self) -> str:
        return f"Campaign(name={self._name!r}, code={self._code!r})"
