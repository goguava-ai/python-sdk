import hashlib
import logging
import warnings
from urllib.parse import urljoin

import httpx

from guava.utils import check_response

logger = logging.getLogger("guava.helpers.rag")


def _content_key(text: str) -> str:
    """Derive a deterministic key from document content."""
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def _prefixed_key(namespace: str | None, key: str) -> str:
    """Apply namespace prefix to a key if set."""
    return f"{namespace}.{key}" if namespace else key


class ServerRAG:
    """RAG via the Guava server API.

    Uploads documents as plain text to the server, which stores them in GCS and
    answers questions using Gemini. No local GCP credentials or vector store setup
    required.

    Handles content-addressed keys, namespace scoping, and reconciliation
    (skip unchanged docs, delete stale docs across runs).

    Args:
        base_url: Guava server base URL (e.g. ``https://app.goguava.ai/``).
        api_key: Guava API key (Bearer token).
        namespace: Optional prefix to scope this instance's documents. Required
            when running multiple instances concurrently for the same user.
    """

    def __init__(self, base_url: str, api_key: str, *, namespace: str | None = None):
        self._base_url = base_url
        self._api_key = api_key
        self._namespace = namespace
        self._tracked_keys: set[str] = set()

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._api_key}"}

    def _url(self, path: str) -> str:
        return urljoin(self._base_url, path)

    # --- Raw HTTP operations (private) ---

    def _upload_document(self, key: str, text: str) -> dict:
        r = httpx.post(
            self._url("v1/rag/documents"),
            json={"key": key, "text": text},
            headers=self._headers(),
            timeout=60.0,
        )
        check_response(r)
        return r.json()

    def _delete_document(self, key: str) -> None:
        r = httpx.delete(
            self._url(f"v1/rag/documents/{key}"),
            headers=self._headers(),
            timeout=30.0,
        )
        check_response(r)

    def _list_documents(self) -> list[dict]:
        r = httpx.get(
            self._url("v1/rag/documents"),
            headers=self._headers(),
            timeout=30.0,
        )
        check_response(r)
        return r.json()

    def _ask(
        self,
        question: str,
        document_keys: list[str] | None = None,
        instructions: str | None = None,
    ) -> str:
        payload: dict = {"question": question}
        if document_keys is not None:
            payload["document_keys"] = document_keys
        if instructions is not None:
            payload["instructions"] = instructions

        r = httpx.post(
            self._url("v1/rag/ask"),
            json=payload,
            headers=self._headers(),
            timeout=120.0,
        )
        check_response(r)
        result = r.json()
        if result.get("warning"):
            warnings.warn(
                f"Guava RAG: {result['warning']}",
                UserWarning,
                stacklevel=3,
            )
        return result["answer"]

    # --- High-level document lifecycle (with namespace + key tracking) ---

    def reconcile(self, documents: list[str], ids: list[str] | None) -> None:
        """Sync server state to match the desired document set.

        - Skips uploading content-addressed documents that already exist.
        - Deletes stale documents from previous runs.
        - When ``ids`` are provided, always re-uploads (content may have changed).
        """
        if ids is not None:
            desired = {_prefixed_key(self._namespace, k): doc for k, doc in zip(ids, documents)}
        else:
            desired = {_prefixed_key(self._namespace, _content_key(doc)): doc for doc in documents}

        existing_keys = {doc["key"] for doc in self._list_documents()}

        if self._namespace:
            scoped = {k for k in existing_keys if k.startswith(f"{self._namespace}.")}
        else:
            scoped = existing_keys

        uploaded = 0
        for key, doc in desired.items():
            if ids is not None or key not in existing_keys:
                self._upload_document(key, doc)
                uploaded += 1
            self._tracked_keys.add(key)

        stale = scoped - set(desired.keys())
        for key in stale:
            self._delete_document(key)

        skipped = len(desired) - uploaded
        logger.info(
            "Reconciled %d document(s): %d uploaded, %d skipped, %d deleted",
            len(desired),
            uploaded,
            skipped,
            len(stale),
        )

    def upsert_document(self, key: str, text: str) -> None:
        """Upload or replace a document by key (with namespace prefix)."""
        full_key = _prefixed_key(self._namespace, key)
        self._upload_document(full_key, text)
        self._tracked_keys.add(full_key)

    def add_document(self, text: str) -> None:
        """Upload a document using a content-derived key (with namespace prefix)."""
        full_key = _prefixed_key(self._namespace, _content_key(text))
        self._upload_document(full_key, text)
        self._tracked_keys.add(full_key)

    def delete_document(self, key: str) -> None:
        """Delete a document by key (with namespace prefix)."""
        full_key = _prefixed_key(self._namespace, key)
        self._delete_document(full_key)
        self._tracked_keys.discard(full_key)

    def clear(self) -> None:
        """Delete all documents tracked by this instance."""
        for key in list(self._tracked_keys):
            self._delete_document(key)
        self._tracked_keys.clear()

    def ask(self, question: str, instructions: str | None = None) -> str:
        """Ask a question against this instance's tracked documents."""
        return self._ask(
            question,
            document_keys=list(self._tracked_keys) if self._tracked_keys else None,
            instructions=instructions,
        )
