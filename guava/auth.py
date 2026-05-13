import json
import logging
import threading
from urllib.parse import urljoin

import httpx

from abc import ABC, abstractmethod
from datetime import datetime, timezone, timedelta

from .utils import cli_config, check_response, get_base_url
from .threading_utils import LazySingleton

logger = logging.getLogger("guava.auth")


class AuthStrategy(ABC):
    @abstractmethod
    def get_headers(self) -> dict[str, str]:
        ...


class APIKeyAuth(AuthStrategy):
    def __init__(self, api_key: str):
        self._api_key = api_key

    def get_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._api_key}"}

TOKEN_REFRESH_BUFFER = timedelta(minutes=1)

class CLIAuth(AuthStrategy):
    def __init__(self):
        config = json.loads(cli_config().read_text())

        self._access_token = config['access_token']
        self._expires_at = datetime.fromtimestamp(config['expires_at'], tz=timezone.utc)
        self._refresh_token = config['refresh_token']
        self._org_id = config["org_id"]
        self._base_url = config.get("base_url", get_base_url())
        self._lock = threading.Lock()

    def refresh_token(self):
        logger.debug("Refreshing access token...")
        resp = httpx.post(
            urljoin(self._base_url, "/oauth/token"),
            data={"grant_type": "refresh_token", "refresh_token": self._refresh_token},
        )
        token = check_response(resp).json()
        self._access_token = token["access_token"]
        self._expires_at = datetime.now(timezone.utc) + timedelta(seconds=token["expires_in"])
        
        if "refresh_token" in token:
            logger.warning("Unexpected refresh token in response.")

    def get_headers(self) -> dict[str, str]:
        with self._lock: # We could move this to double-checked if performance is lacking.
            now = datetime.now(timezone.utc)
            if self._expires_at - now <= TOKEN_REFRESH_BUFFER:
                self.refresh_token()
            
        return {
            "Authorization": f"Bearer {self._access_token}",
            "x-guava-org-id": self._org_id,
        }

cli_auth = LazySingleton(CLIAuth)
