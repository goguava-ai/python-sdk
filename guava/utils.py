import os
import functools
import warnings
import httpx
import json
import sys
from pathlib import Path

from typing import Callable, TypeVar, Any, cast
from .threading_utils import FirstEntry

DEFAULT_BASE_URL: str = "https://app.goguava.ai/"

def get_base_url() -> str:
    if "GUAVA_BASE_URL" in os.environ:
        return os.environ["GUAVA_BASE_URL"]
    elif cli_config().exists():
        # Try to read the base_url from the CLI config.
        config = json.loads(cli_config().read_text())
        return config.get("base_url", DEFAULT_BASE_URL)
    else:
        return DEFAULT_BASE_URL


def check_response(response: httpx.Response) -> httpx.Response:
    """
    By default, httpx raise_for_status doesn't include the response body.
    This wrapper catches the exception and re-raises it with the body included.
    """
    try:
        response.raise_for_status() # nosemgrep: python-raise-for-status-no-args
        return response
    except httpx.HTTPStatusError as exc:
        try:
            body: str = exc.response.read().decode()
        except Exception:
            body = "<could not read body>"

        msg = f"HTTP {response.status_code} {response.reason_phrase} for url '{response.url}', Body: {body}"
        raise httpx.HTTPStatusError(msg, request=exc.request, response=exc.response) from None


F = TypeVar("F", bound=Callable[..., Any])

def preview(feature: str) -> Callable[[F], F]:
    """Decorator that emits warnings for preview features."""
    
    def decorator(fn: F) -> F:
        first_entry = FirstEntry()

        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            if first_entry.claim():
                warnings.warn(
                    f'Feature "{feature}" is in preview and may change without notice.',
                    category=UserWarning,
                    stacklevel=2,
                )
            return fn(*args, **kwargs)

        return cast(F, wrapper)
    
    return decorator

def deprecated(feature: str) -> Callable[[F], F]:
    """Decorator that emits warnings for deprecated features."""
    
    def decorator(fn: F) -> F:
        first_entry = FirstEntry()

        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            if first_entry.claim():
                warnings.warn(
                    f'Feature "{feature}" is deprecated and may be removed in future versions.',
                    category=UserWarning,
                    stacklevel=2,
                )
            return fn(*args, **kwargs)

        return cast(F, wrapper)
    
    return decorator

class NoOpLogger:
    def debug(self, *args: Any, **kwargs: Any) -> None: pass
    def info(self, *args: Any, **kwargs: Any) -> None: pass
    def warning(self, *args: Any, **kwargs: Any) -> None: pass
    def error(self, *args: Any, **kwargs: Any) -> None: pass
    def exception(self, *args: Any, **kwargs: Any) -> None: pass
    def critical(self, *args: Any, **kwargs: Any) -> None: pass
    def log(self, *args: Any, **kwargs: Any) -> None: pass
    
def check_exactly_one(*args) -> bool:
    return sum(arg is not None for arg in args) == 1

def is_jsonable(value) -> bool:
    try:
        json.dumps(value)
        return True
    except (TypeError, ValueError):
        return False
    
def platform_config_dir() -> Path:
    """
    Simple no-third-party equivalent of Rust dirs::config_dir().

    Raises RuntimeError if the directory cannot be determined.
    """
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA")
        if not appdata:
            raise RuntimeError("Could not determine config directory: APPDATA is not set")
        return Path(appdata)

    try:
        home = Path.home()
    except RuntimeError as exc:
        raise RuntimeError("Could not determine config directory: home directory is unknown") from exc

    if sys.platform == "darwin":
        return home / "Library" / "Application Support"

    xdg_config_home = os.environ.get("XDG_CONFIG_HOME")
    if xdg_config_home:
        return Path(xdg_config_home)

    return home / ".config"

def cli_config() -> Path:
    return platform_config_dir() / "guava" / "config.json"
