import threading
from typing import Any, Callable, Generic, ParamSpec, TypeVar

T = TypeVar("T")
P = ParamSpec("P")


def create_daemon_thread(target: Callable[P, Any], *args: P.args, **kwargs: P.kwargs) -> threading.Thread:
    """Create an unstarted daemon thread that runs target(*args, **kwargs).

    Unlike ``threading.Thread(target=..., args=...)``, the arguments are
    typechecked against the target's signature.

    Args:
        target: The callable to run on the thread.
        *args: Positional arguments to pass to the target.
        **kwargs: Keyword arguments to pass to the target.

    Returns:
        The unstarted thread.
    """
    return threading.Thread(target=target, args=args, kwargs=kwargs, daemon=True)  # nosemgrep: python-no-threading-thread


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