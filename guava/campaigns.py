# Doesn't have to be its own file
import httpx
from guava.types import OutreachModality, E164PhoneNumber
from typing import Optional, Any
from guava.client import Client
from pydantic import BaseModel, Field

import logging

from guava.utils import check_response

logger = logging.getLogger(__name__)

class Contact(BaseModel):
    phone_number: E164PhoneNumber
    data: dict[str, Any] = Field(default_factory=dict)
    outreach_modalities: Optional[list[OutreachModality]] = None


class OutboundCampaign:
    def __init__(self, data: dict):
        self.id = data.get("id")
        self.name = data.get("name")
        self._data = data
        self._client = Client()

    def upload_contacts(
        self, 
        contacts: list[Contact], 
        allow_duplicates: bool = False, 
        accepted_terms_of_service: bool = False,
        # easy way to be add to all the contacts
        outreach_modalities: list[OutreachModality] | None = None,
    ):
        if outreach_modalities:
            for contact in contacts:
                # prefer contact's own modalities if set
                contact.outreach_modalities = contact.outreach_modalities or outreach_modalities

        response = httpx.post(
            self._client.get_http_url(f'v1/campaigns/{self.id}/contacts'),
            params={
                'allow_duplicates': str(allow_duplicates).lower(),
                'accepted_terms_of_service': str(accepted_terms_of_service).lower(),
            },
            json={'contacts': [c.model_dump() for c in contacts]},
            headers=self._client._get_headers(),
        )
        check_response(response)
        return response.json()

    def get_status(self):
        response = httpx.get(
            self._client.get_http_url(f'v1/campaigns/{self.id}/status'),
            headers=self._client._get_headers(),
        )
        check_response(response)
        return response.json()

    def update(self, **kwargs):
        response = httpx.patch(
            self._client.get_http_url(f'v1/campaigns/{self.id}'),
            json=kwargs,
            headers=self._client._get_headers(),
        )
        check_response(response)
        updated = response.json()
        self._data = updated
        self.name = updated.get("name", self.name)
        return updated

    def delete(self):
        response = httpx.delete(
            self._client.get_http_url(f'v1/campaigns/{self.id}'),
            headers=self._client._get_headers(),
        )
        check_response(response)
        return response.json()

    def __repr__(self):
        return f"OutboundCampaign(name={self.name!r}, id={self.id!r})"


def list_campaigns() -> list[OutboundCampaign]:
    client = Client()
    response = httpx.get(
        client.get_http_url('v1/campaigns'),
        headers=client._get_headers(),
    )
    check_response(response)
    return [OutboundCampaign(c) for c in response.json()]


def get_or_create_campaign(
    campaign_name: str,
    origin_phone_numbers: Optional[list] = None,
    calling_windows: Optional[list] = None,
    start_date: Optional[str] = None,
    max_concurrency: Optional[int] = None,
    max_attempts: Optional[int] = None,
    timezone: Optional[str] = None,
    end_date: Optional[str] = None,
    description: str | None = None,
) -> OutboundCampaign:
    """
    calling_windows: list of {"day": 0-6, "start_time": "HH:MM", "end_time": "HH:MM"}
    start_date / end_date: "YYYY-MM-DD"

    origin_phone_numbers, calling_windows, and start_date are only required when
    creating a new campaign. If the campaign already exists, only campaign_name is needed.
    """
    client = Client()

    request_json: dict = {'name': campaign_name}
    if origin_phone_numbers is not None:
        request_json['origin_phone_numbers'] = origin_phone_numbers
    if calling_windows is not None:
        request_json['calling_windows'] = calling_windows
    if start_date is not None:
        request_json['start_date'] = start_date
    if end_date is not None:
        request_json['end_date'] = end_date
    if max_concurrency is not None:
        request_json['max_concurrency'] = max_concurrency
    if max_attempts is not None:
        request_json['max_attempts'] = max_attempts
    if timezone is not None:
        request_json['timezone'] = timezone
    if description is not None:
        request_json['description'] = description
    response = httpx.post(
        client.get_http_url('v1/campaigns'), json=request_json,
        headers=client._get_headers(),
    )
    check_response(response)
    return OutboundCampaign(response.json())



