# Doesn't have to be its own file
import httpx
import os
import platform
import urllib.parse
from importlib.metadata import version, PackageNotFoundError
from guava.types import OutreachModality
from typing import Optional

import logging

from guava.utils import check_response

logger = logging.getLogger(__name__)

SDK_NAME = "python-sdk"
try:
    __version__ = version("gridspace-guava")
except PackageNotFoundError:
    __version__ = "0+unknown"


DEFAULT_BASE_URL = "http://localhost:8000/"

api_key = os.environ.get('GUAVA_API_KEY')
HEADERS = {
    "Authorization": f"Bearer {api_key}",
    "x-guava-platform": platform.system(),
    "x-guava-runtime": platform.python_implementation(),
    "x-guava-runtime-version": platform.python_version(),
    "x-guava-sdk": SDK_NAME,
    "x-guava-sdk-version": __version__,
}
if 'GUAVA_BASE_URL' in os.environ:
    base_url = os.environ['GUAVA_BASE_URL']
else:
    base_url = DEFAULT_BASE_URL


class OutboundCampaign:
    def __init__(self, data: dict):
        self.id = data.get("id")
        self.name = data.get("name")
        self._data = data

    def upload_contacts(
        self, 
        contacts: list, 
        allow_duplicates: bool = False, 
        accepted_terms_of_service: bool = False,
        # easy way to be add to all the contacts
        outreach_modalities: list[OutreachModality] | None = None,
    ):
        if outreach_modalities:
            for contact in contacts:
                # prefer contact's own modalities if set
                contact['outreach_modalities'] = contact.get('outreach_modalities') or outreach_modalities
        response = httpx.post(
            urllib.parse.urljoin(base_url, f'v1/campaigns/{self.id}/contacts'),
            params={
                'allow_duplicates': str(allow_duplicates).lower(),
                'accepted_terms_of_service': str(accepted_terms_of_service).lower(),
            },
            json={'contacts': contacts},
            headers=HEADERS,
        )
        check_response(response)
        return response.json()

    def get_status(self):
        response = httpx.get(
            urllib.parse.urljoin(base_url, f'v1/campaigns/{self.id}/status'),
            headers=HEADERS,
        )
        check_response(response)
        return response.json()

    def update(self, **kwargs):
        response = httpx.patch(
            urllib.parse.urljoin(base_url, f'v1/campaigns/{self.id}'),
            json=kwargs,
            headers=HEADERS,
        )
        check_response(response)
        updated = response.json()
        self._data = updated
        self.name = updated.get("name", self.name)
        return updated

    def delete(self):
        response = httpx.delete(
            urllib.parse.urljoin(base_url, f'v1/campaigns/{self.id}'),
            headers=HEADERS,
        )
        check_response(response)
        return response.json()

    def __repr__(self):
        return f"OutboundCampaign(name={self.name!r}, id={self.id!r})"


def list_campaigns() -> list[OutboundCampaign]:
    response = httpx.get(
        urllib.parse.urljoin(base_url, 'v1/campaigns'),
        headers=HEADERS,
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
        urllib.parse.urljoin(base_url, 'v1/campaigns'), json=request_json,
        headers=HEADERS,
    )
    check_response(response)
    return OutboundCampaign(response.json())



