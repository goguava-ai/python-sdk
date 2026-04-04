import logging
import time
from abc import ABC, abstractmethod

logger = logging.getLogger("guava.helpers.rag")

DEFAULT_EMBEDDING_MODEL = "gemini-embedding-001"
DEFAULT_EMBEDDING_DIM = 768


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


class VertexAIEmbedding(EmbeddingModel):
    """Embedding via Vertex AI (Gemini).

    Uses different task types for document indexing vs. query search, which
    improves retrieval quality over using a single generic embedding.

    The caller is responsible for supplying a configured ``google.genai.Client``.
    Guava helpers never create API clients on your behalf — you control
    credentials, project selection, and quota settings.

    Args:
        client: A configured ``google.genai.Client`` instance.
        model: Vertex AI embedding model name.
        dimensionality: Output vector size.
    """

    def __init__(
        self,
        *,
        client,
        model: str = DEFAULT_EMBEDDING_MODEL,
        dimensionality: int = DEFAULT_EMBEDDING_DIM,
    ):
        self._model = model
        self._dimensionality = dimensionality
        self._client = client

    def ndims(self) -> int:
        return self._dimensionality

    def embed(self, texts: list[str]) -> list[list[float]]:
        return self._embed(texts, "RETRIEVAL_DOCUMENT")

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        t0 = time.perf_counter()
        result = self._embed(texts, "RETRIEVAL_DOCUMENT")
        logger.info("embed_documents: %d text(s) in %.3fs", len(texts), time.perf_counter() - t0)
        return result

    def embed_query(self, text: str) -> list[float]:
        t0 = time.perf_counter()
        result = self._embed([text], "QUESTION_ANSWERING")[0]
        logger.info("embed_query in %.3fs", time.perf_counter() - t0)
        return result

    def _embed(self, texts: list[str], task_type: str) -> list[list[float]]:
        from google import genai

        response = self._client.models.embed_content(
            model=self._model,
            contents=texts,
            config=genai.types.EmbedContentConfig(
                output_dimensionality=self._dimensionality,
                task_type=task_type,
            ),
        )
        return [e.values for e in response.embeddings]


class PineconeInferenceEmbedding(EmbeddingModel):
    """Embedding via Pinecone's hosted Inference API.

    Uses different input types for document indexing vs. query search.
    No additional API key required beyond the Pinecone API key.

    Args:
        pc: A ``Pinecone`` client instance.
        model: Pinecone inference model name.
        dimensionality: Output vector size.
    """

    def __init__(self, pc, model: str = "multilingual-e5-large", dimensionality: int = 1024):
        self._pc = pc
        self._model = model
        self._dimensionality = dimensionality

    def ndims(self) -> int:
        return self._dimensionality

    def embed(self, texts: list[str]) -> list[list[float]]:
        return self.embed_documents(texts)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        response = self._pc.inference.embed(
            model=self._model,
            inputs=texts,
            parameters={"input_type": "passage", "truncate": "END"},
        )
        return [e["values"] for e in response]

    def embed_query(self, text: str) -> list[float]:
        response = self._pc.inference.embed(
            model=self._model,
            inputs=[text],
            parameters={"input_type": "query", "truncate": "END"},
        )
        return response[0]["values"]
