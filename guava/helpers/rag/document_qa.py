import logging
import os
import time
import warnings

from guava.telemetry import telemetry_client

from .chunking import chunk_document
from .generation import GenerationModel
from .vectorstore import VectorStore

logger = logging.getLogger("guava.helpers.rag")

_DEFAULT_INSTRUCTIONS = (
    "You are a virtual agent. Your task is to answer questions using "
    "ONLY the provided supporting document excerpts. If the answer is not "
    "in the provided context, say so. Just answer the question — do not offer "
    "any follow-ups."
)


def _default_server_rag(namespace=None):
    from .server_rag import ServerRAG
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
        from guava.helpers.rag import LanceDBStore, VertexAIEmbedding, VertexAIGeneration

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
