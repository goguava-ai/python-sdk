import logging
import os
import time
import warnings
from abc import ABC, abstractmethod

from guava.telemetry import telemetry_client

logger = logging.getLogger("guava.helpers.rag")


# ── VectorStore ────────────────────────────────────────────────────────────────


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


# ── EmbeddingModel ─────────────────────────────────────────────────────────────


class EmbeddingModel(ABC):
    """Abstract base class for embedding models used in Guava RAG helpers.

    Subclass and implement ``embed()`` and ``ndims()``. Optionally override
    ``embed_documents()`` and ``embed_query()`` to use task-specific behaviour
    (e.g. different task types for Vertex AI, different input types for Pinecone).
    """

    @abstractmethod
    def ndims(self) -> int:
        """Return the dimensionality of the produced embedding vectors."""
        ...

    @abstractmethod
    def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of texts into vectors."""
        ...

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embed texts for document indexing. Defaults to ``embed()``."""
        return self.embed(texts)

    def embed_query(self, text: str) -> list[float]:
        """Embed a single query for search. Defaults to ``embed([text])[0]``."""
        return self.embed([text])[0]


# ── GenerationModel ────────────────────────────────────────────────────────────


class GenerationModel(ABC):
    """Abstract base class for QA generation models used in Guava RAG helpers.

    Subclass and implement ``generate()``.
    """

    @abstractmethod
    def generate(self, prompt: str, *, system_instruction: str | None = None) -> str:
        """Generate a response for the given prompt.

        Args:
            prompt: The user prompt (e.g. context + question).
            system_instruction: Optional system-level instruction.
        """
        ...


# ── chunk_document ─────────────────────────────────────────────────────────────


def chunk_document(document: str, chunk_size: int = 5000, overlap: int = 200) -> list[str]:
    """Split a document into overlapping chunks on paragraph boundaries.

    Paragraphs are grouped until *chunk_size* characters are reached, then
    a new chunk begins. When *overlap* > 0, the last paragraph of each chunk
    is carried over to the next chunk to preserve cross-boundary context.
    """
    paragraphs = [p.strip() for p in document.split("\n\n") if p.strip()]

    chunks: list[str] = []
    current_chunk: list[str] = []
    current_length = 0

    for paragraph in paragraphs:
        paragraph_length = len(paragraph)
        if current_length + paragraph_length > chunk_size and current_chunk:
            chunks.append("\n\n".join(current_chunk))
            # Carry the last paragraph into the next chunk for overlap
            if overlap > 0 and current_chunk:
                last = current_chunk[-1]
                current_chunk = [last]
                current_length = len(last)
            else:
                current_chunk = []
                current_length = 0
        current_chunk.append(paragraph)
        current_length += paragraph_length

    if current_chunk:
        chunks.append("\n\n".join(current_chunk))

    return chunks


# ── DocumentQA ─────────────────────────────────────────────────────────────────

_DEFAULT_INSTRUCTIONS = (
    "You are a virtual agent. Your task is to answer questions using "
    "ONLY the provided supporting document excerpts. If the answer is not "
    "in the provided context, say so. Just answer the question — do not offer "
    "any follow-ups."
)


def _default_server_rag(namespace=None):
    from guava.helpers.server_rag import ServerRAG
    from guava.utils import get_base_url

    return ServerRAG(
        base_url=get_base_url(), api_key=os.environ["GUAVA_API_KEY"], namespace=namespace
    )


@telemetry_client.track_class()
class DocumentQA:
    """High-level question-answering over documents using a pluggable vector store.

    Chunks and indexes documents into the store, then retrieves relevant
    chunks and generates an answer via the generation model.

    Pass ``documents`` to bulk-load content at construction time. Optionally
    pass ``ids`` alongside ``documents`` to make them individually updatable
    via ``upsert_document`` / ``delete_document`` later.

    **Server mode** (default): when no explicit ``store`` is provided,
    ``DocumentQA`` delegates to the Guava server-side RAG API. Documents are
    uploaded to the server; no local vector store or GCP credentials are needed.

    Documents are content-addressed by default — their key is derived from a
    hash of the content. This means:

    - Unchanged documents are not re-uploaded across runs.
    - Removed documents are automatically deleted from the server when
      you create a new instance with a different `documents` list.
    - Multiple instances can coexist by providing a `namespace` to scope
      each instance's documents independently.

    Local mode: pass an explicit ``store`` and ``generation_model``. You are
    responsible for constructing these with your own API clients — Guava helpers
    never create API clients on your behalf.

    Example::

        qa = DocumentQA(documents=[policy_text, faq_text])
        answer = qa.ask("What is the deductible?")

    Example (multi-instance with namespace)::

        dental = DocumentQA(documents=dental_docs, namespace="dental")
        restaurant = DocumentQA(documents=restaurant_docs, namespace="restaurant")
        dental.ask("What is the copay?")        # only searches dental docs
        restaurant.ask("Do you have vegan?")    # only searches restaurant docs

    Example (local mode)::

        from google import genai
        from guava.helpers.lancedb import LanceDBStore
        from guava.helpers.vertexai import VertexAIEmbedding, VertexAIGeneration

        client = genai.Client(vertexai=True, project="my-project", location="us-central1")
        store = LanceDBStore("gs://my-bucket/lancedb", embedding_model=VertexAIEmbedding(client=client))
        qa = DocumentQA(store=store, generation_model=VertexAIGeneration(client=client))
        qa.upsert_document("policy", my_text)
        answer = qa.ask("What is the deductible?")

    Args:
        store: Vector store to index and search documents. When omitted, server-side
            RAG is used automatically.
        documents: Documents to index at construction time.
        ids: Optional IDs for each document, enabling later upsert/delete.
            When omitted, keys are derived from content hashes.
        chunk_size: Maximum characters per chunk (local mode only).
        chunk_overlap: Overlap between consecutive chunks in characters (local mode only).
        instructions: System instruction for the generation model.
        generation_model: Generation model for producing answers (local mode only).
        server_rag: Explicit ``ServerRAG`` instance. When provided, forces server
            mode regardless of other arguments.
        namespace: Stable string to scope this instance's documents on the server.
            Required when running multiple ``DocumentQA`` instances concurrently
            for the same user. Ignored in local mode.
    """

    def __init__(
        self,
        store: VectorStore | None = None,
        documents: list[str] | str | None = None,
        ids: list[str] | None = None,
        chunk_size: int = 5000,
        chunk_overlap: int = 200,
        instructions: str | None = None,
        *,
        generation_model: GenerationModel | None = None,
        server_rag=None,
        namespace: str | None = None,
    ):
        self.instructions = instructions
        self._chunk_size = chunk_size
        self._chunk_overlap = chunk_overlap
        self._doc_chunks: dict[str, list[str]] = {}

        # Determine mode: server or local.
        if server_rag is not None:
            self._server_rag = server_rag
        elif store is None:
            self._server_rag = _default_server_rag(namespace)
        else:
            self._server_rag = None

        if self._server_rag is not None:
            # Server mode — no local store or generation model needed.
            warnings.warn(
                "Guava server-side RAG is active. This mode is intended for testing and simple use cases. "
                "For larger document sets or more advanced retrieval, use a dedicated vector store "
                "(LanceDB, Pinecone, ChromaDB, or pgvector). "
                "Your documents are stored securely, but server-side RAG does not carry the data "
                "compliance guarantees available in the rest of Guava.",
                UserWarning,
                stacklevel=2,
            )
            self.store = None
            self._generation_model = None

            if documents is not None:
                if isinstance(documents, str):
                    documents = [documents]
                if ids is not None:
                    if len(ids) != len(documents):
                        raise ValueError(
                            f"ids length ({len(ids)}) must match documents length ({len(documents)})"
                        )
                self._server_rag.reconcile(documents, ids)
        else:
            # Local mode — caller supplies store and generation_model.
            if generation_model is None:
                raise ValueError(
                    "In local mode, provide an explicit 'generation_model' "
                    "(e.g. VertexAIGeneration(client=your_client))."
                )
            assert store is not None
            self.store = store
            self._generation_model = generation_model

            if documents is not None:
                if isinstance(documents, str):
                    documents = [documents]
                if ids is not None:
                    if len(ids) != len(documents):
                        raise ValueError(
                            f"ids length ({len(ids)}) must match documents length ({len(documents)})"
                        )
                    logger.info(
                        "Indexing %d document(s) with keys into vector store...", len(documents)
                    )
                    t0 = time.perf_counter()
                    all_ids: list[str] = []
                    all_chunks: list[str] = []
                    for key, doc in zip(ids, documents):
                        chunks = chunk_document(doc, chunk_size, chunk_overlap)
                        chunk_ids = [f"{key}:{i}" for i in range(len(chunks))]
                        self._doc_chunks[key] = chunk_ids
                        all_ids.extend(chunk_ids)
                        all_chunks.extend(chunks)
                    self.store.upsert_texts(all_ids, all_chunks)
                    logger.info(
                        "Indexed %d document(s) (%d chunks) in %.3fs total",
                        len(documents),
                        len(all_chunks),
                        time.perf_counter() - t0,
                    )
                else:
                    logger.info("Indexing %d document(s) into vector store...", len(documents))
                    chunks: list[str] = []
                    for doc in documents:
                        chunks.extend(chunk_document(doc, chunk_size, chunk_overlap))
                    t0 = time.perf_counter()
                    self.store.add_texts(chunks)
                    logger.info(
                        "Indexed %d chunks in %.3fs total", len(chunks), time.perf_counter() - t0
                    )

    def upsert_document(self, key: str, text: str) -> None:
        """Add or replace a document by key.

        In server mode, uploads the full document text to the Guava server.

        In local mode, chunks the text and upserts each chunk into the store
        using deterministic IDs derived from the document key. If the document
        previously had more chunks (e.g. it got shorter), the stale chunks are
        deleted automatically.
        """
        if self._server_rag is not None:
            self._server_rag.upsert_document(key, text)
            return

        old_ids = self._doc_chunks.get(key, [])
        chunks = chunk_document(text, self._chunk_size, self._chunk_overlap)
        new_ids = [f"{key}:{i}" for i in range(len(chunks))]

        assert self.store is not None
        stale_ids = old_ids[len(new_ids) :]
        if stale_ids:
            self.store.delete(stale_ids)

        self.store.upsert_texts(new_ids, chunks)
        self._doc_chunks[key] = new_ids

    def add_document(self, text: str) -> None:
        """Add a document to the store.

        In server mode, uploads using a content-derived key.
        """
        if self._server_rag is not None:
            self._server_rag.add_document(text)
            return

        chunks = chunk_document(text, self._chunk_size, self._chunk_overlap)
        assert self.store is not None
        self.store.add_texts(chunks)

    def delete_document(self, key: str) -> None:
        """Delete a previously upserted document by key."""
        if self._server_rag is not None:
            self._server_rag.delete_document(key)
            return

        assert self.store is not None
        old_ids = self._doc_chunks.pop(key, [])
        if old_ids:
            self.store.delete(old_ids)

    def clear(self) -> None:
        """Remove all documents from the store.

        In server mode, deletes only the documents managed by this instance.
        """
        if self._server_rag is not None:
            self._server_rag.clear()
            return

        assert self.store is not None
        self.store.clear()
        self._doc_chunks.clear()

    def ask(self, question: str, k: int = 5) -> str:
        """Retrieve relevant chunks and generate an answer.

        In server mode, delegates entirely to the Guava server.
        Only the documents managed by this instance are queried. The ``k``
        parameter is ignored in server mode since the full document context is
        used rather than vector similarity search.
        """
        if self._server_rag is not None:
            return self._server_rag.ask(question, instructions=self.instructions)

        assert self.store is not None
        assert self._generation_model is not None
        t0 = time.perf_counter()
        chunks = self.store.search(question, k=k)
        logger.info("retrieve: %.3fs", time.perf_counter() - t0)
        context = "\n\n---\n\n".join(chunks)
        instructions = self.instructions or _DEFAULT_INSTRUCTIONS
        return self._generation_model.generate(
            f"Context:\n{context}\n\nQuestion: {question}",
            system_instruction=instructions,
        )
