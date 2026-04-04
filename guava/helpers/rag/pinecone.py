import logging
import uuid

from .embedding import EmbeddingModel, PineconeInferenceEmbedding
from .vectorstore import VectorStore

logger = logging.getLogger("guava.helpers.rag")


class PineconeVectorStore(VectorStore):
    """Vector store backed by Pinecone.

    Uses Pinecone Inference (``multilingual-e5-large``, 1024-dim) for embedding
    by default — no additional API key required beyond ``PINECONE_API_KEY``.
    Pass a custom ``embedding_model`` to use a different model.

    The Pinecone index is created automatically if it does not already exist,
    using the dimensionality reported by the embedding model.

    Args:
        api_key: Pinecone API key. If omitted, reads ``PINECONE_API_KEY``
            from the environment via the Pinecone client defaults.
        index_name: Name of the Pinecone index. Defaults to ``"guava-chunks"``.
        cloud: Pinecone serverless cloud provider (used only at index-creation
            time). Defaults to ``"aws"``.
        region: Pinecone serverless region (used only at index-creation time).
            Defaults to ``"us-east-1"``.
        embedding_model: Embedding model to use. Defaults to
            ``PineconeInferenceEmbedding`` with ``multilingual-e5-large``.
    """

    def __init__(
        self,
        api_key: str | None = None,
        index_name: str = "guava-chunks",
        cloud: str = "aws",
        region: str = "us-east-1",
        *,
        embedding_model: EmbeddingModel | None = None,
    ):
        try:
            from pinecone import Pinecone, ServerlessSpec  # ty: ignore[unresolved-import]
        except ImportError:
            raise ImportError(
                "pinecone is not installed. Run: pip install 'gridspace-guava[pinecone]'"
            ) from None
        self._pc = Pinecone(api_key=api_key) if api_key else Pinecone()
        self._embedding_model = embedding_model or PineconeInferenceEmbedding(pc=self._pc)
        if index_name not in [idx.name for idx in self._pc.list_indexes()]:
            logger.info(
                "Creating Pinecone index '%s' (dim=%d)...",
                index_name,
                self._embedding_model.ndims(),
            )
            self._pc.create_index(
                name=index_name,
                dimension=self._embedding_model.ndims(),
                metric="cosine",
                spec=ServerlessSpec(cloud=cloud, region=region),
            )
        self._index = self._pc.Index(index_name)

    def add_texts(self, texts: list[str]) -> list[str]:
        ids = [str(uuid.uuid4()) for _ in texts]
        embeddings = self._embedding_model.embed_documents(texts)
        vectors = [
            {"id": id_, "values": emb, "metadata": {"text": t}}
            for id_, t, emb in zip(ids, texts, embeddings)
        ]
        for i in range(0, len(vectors), 100):
            self._index.upsert(vectors=vectors[i : i + 100])
        logger.info("Pinecone: upserted %d chunks.", len(texts))
        return ids

    def upsert_texts(self, ids: list[str], texts: list[str]) -> None:
        embeddings = self._embedding_model.embed_documents(texts)
        vectors = [
            {"id": id_, "values": emb, "metadata": {"text": t}}
            for id_, t, emb in zip(ids, texts, embeddings)
        ]
        for i in range(0, len(vectors), 100):
            self._index.upsert(vectors=vectors[i : i + 100])

    def delete(self, ids: list[str]) -> None:
        self._index.delete(ids=ids)

    def search(self, query: str, k: int = 5) -> list[str]:
        vector = self._embedding_model.embed_query(query)
        results = self._index.query(vector=vector, top_k=k, include_metadata=True)
        return [match.metadata["text"] for match in results.matches]

    def clear(self) -> None:
        self._index.delete(delete_all=True)

    def count(self) -> int:
        return self._index.describe_index_stats().total_vector_count
