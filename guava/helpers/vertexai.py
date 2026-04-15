import logging
import time

from .rag import EmbeddingModel, GenerationModel

logger = logging.getLogger("guava.helpers.rag")

DEFAULT_EMBEDDING_MODEL = "gemini-embedding-001"
DEFAULT_EMBEDDING_DIM = 768
DEFAULT_QA_MODEL = "gemini-2.5-flash"


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


class VertexAIGeneration(GenerationModel):
    """QA generation via Vertex AI (Gemini).

    The caller is responsible for supplying a configured ``google.genai.Client``.
    Guava helpers never create API clients on your behalf — you control
    credentials, project selection, and quota settings.

    Args:
        client: A configured ``google.genai.Client`` instance.
        model: Gemini model name.
    """

    def __init__(self, *, client, model: str = DEFAULT_QA_MODEL):
        self._model = model
        self._client = client

    def generate(self, prompt: str, *, system_instruction: str | None = None) -> str:
        t0 = time.perf_counter()
        config = {"system_instruction": system_instruction} if system_instruction else {}
        response = self._client.models.generate_content(
            model=self._model,
            contents=prompt,
            config=config,
        )
        logger.info("generate_content: %.3fs", time.perf_counter() - t0)
        return response.text
