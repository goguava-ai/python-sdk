import logging
import time
from abc import ABC, abstractmethod

logger = logging.getLogger("guava.helpers.rag")

DEFAULT_QA_MODEL = "gemini-2.5-flash"


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
