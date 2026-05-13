import threading
from typing import Callable, Generic, TypeVar

T = TypeVar("T")


class LazySingleton(Generic[T]):
    """Thread-safe lazy singleton that initializes its value on first access."""

    def __init__(self, factory: Callable[[], T]) -> None:
        self._factory = factory
        self._instance: T | None = None
        self._lock = threading.Lock()

    def get(self) -> T:
        """Return the singleton instance, creating it on the first call."""
        if self._instance is None:
            with self._lock:
                if self._instance is None:
                    self._instance = self._factory()
        return self._instance


class FirstEntry:
    """Thread-safe flag that distinguishes the first caller from all subsequent ones."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._claimed = False

    def claim(self) -> bool:
        """Claim first entry. Returns True for the first caller, False for all subsequent callers."""
        # Double-checked locking fast-path
        if self._claimed:
            return False
        
        with self._lock:
            if self._claimed:
                return False
            self._claimed = True
            return True