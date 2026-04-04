from abc import ABC, abstractmethod


class VectorStore(ABC):
    """Abstract base class for vector stores used in Guava RAG helpers.

    Implementations handle embedding internally — callers pass plain text
    and get plain text back. This keeps the DocumentQA interface simple
    and lets each backend choose its own embedding strategy.
    """

    @abstractmethod
    def add_texts(self, texts: list[str]) -> list[str]:
        """Embed and store text chunks. Returns a list of IDs, one per chunk.

        IDs are opaque strings assigned by the store. Pass them to delete()
        to remove specific chunks later (e.g. when a source article changes).
        May be called multiple times; each call appends to the existing store.
        """
        ...

    @abstractmethod
    def upsert_texts(self, ids: list[str], texts: list[str]) -> None:
        """Add or replace text chunks by caller-provided IDs.

        If a chunk with a given ID already exists, it is replaced (re-embedded
        and overwritten). Otherwise it is inserted as new. This is the
        preferred method for incremental updates where the caller controls
        chunk identity.
        """
        ...

    @abstractmethod
    def delete(self, ids: list[str]) -> None:
        """Delete chunks by the IDs returned from add_texts or upsert_texts."""
        ...

    @abstractmethod
    def search(self, query: str, k: int = 5) -> list[str]:
        """Return the top-k most relevant text chunks for the query."""
        ...

    @abstractmethod
    def clear(self) -> None:
        """Remove all stored data."""
        ...

    @abstractmethod
    def count(self) -> int:
        """Return the number of stored chunks."""
        ...
