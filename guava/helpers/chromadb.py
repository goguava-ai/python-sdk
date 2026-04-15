import logging

from .rag import EmbeddingModel, VectorStore

logger = logging.getLogger("guava.helpers.rag")


class ChromaVectorStore(VectorStore):
    """Vector store backed by ChromaDB (local or remote).

    By default, ChromaDB handles embedding internally using its built-in
    ``all-MiniLM-L6-v2`` model — no external embedding API is required.
    Pass a custom ``embedding_model`` to use a different model instead.

    Embeddings persist to disk across restarts when a ``path`` is provided.

    Args:
        path: Directory for persistent storage. Defaults to ``"./chroma_data"``.
            Pass ``None`` to use an in-memory (ephemeral) client.
        collection_name: Name of the ChromaDB collection. Defaults to ``"chunks"``.
        embedding_model: Optional embedding model. When provided, embeddings are
            computed externally and passed to ChromaDB rather than using its
            built-in model.
    """

    def __init__(
        self,
        path: str | None = "./chroma_data",
        collection_name: str = "chunks",
        *,
        embedding_model: EmbeddingModel | None = None,
    ):
        try:
            import chromadb as _chromadb
        except ImportError:
            raise ImportError(
                "chromadb is not installed. Run: pip install 'gridspace-guava[chromadb]'"
            ) from None
        if path is None:
            self._db = _chromadb.Client()  # ty: ignore[unresolved-attribute]
        else:
            self._db = _chromadb.PersistentClient(path=path)  # ty: ignore[unresolved-attribute]
        self._collection = self._db.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"},
        )
        self._embedding_model = embedding_model
        self._offset = self._collection.count()

    def add_texts(self, texts: list[str]) -> list[str]:
        ids = [str(self._offset + i) for i in range(len(texts))]
        if self._embedding_model is not None:
            embeddings = self._embedding_model.embed_documents(texts)
            self._collection.add(embeddings=embeddings, documents=texts, ids=ids)
        else:
            self._collection.add(documents=texts, ids=ids)
        self._offset += len(texts)
        logger.info("ChromaDB: added %d chunks.", len(texts))
        return ids

    def upsert_texts(self, ids: list[str], texts: list[str]) -> None:
        if self._embedding_model is not None:
            embeddings = self._embedding_model.embed_documents(texts)
            self._collection.upsert(embeddings=embeddings, documents=texts, ids=ids)
        else:
            self._collection.upsert(ids=ids, documents=texts)

    def delete(self, ids: list[str]) -> None:
        self._collection.delete(ids=ids)

    def search(self, query: str, k: int = 5) -> list[str]:
        n = min(k, self._collection.count())
        if n == 0:
            return []
        if self._embedding_model is not None:
            query_embedding = self._embedding_model.embed_query(query)
            results = self._collection.query(query_embeddings=[query_embedding], n_results=n)
        else:
            results = self._collection.query(query_texts=[query], n_results=n)
        return results["documents"][0]

    def clear(self) -> None:
        existing_ids = self._collection.get(include=[])["ids"]
        if existing_ids:
            self._collection.delete(ids=existing_ids)
        self._offset = 0

    def count(self) -> int:
        return self._collection.count()
