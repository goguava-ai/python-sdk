import logging
import time
import uuid

from .embedding import EmbeddingModel
from .vectorstore import VectorStore

logger = logging.getLogger("guava.helpers.rag")


class LanceDBStore(VectorStore):
    """Vector store backed by LanceDB (local or GCS).

    Works with local paths (``"./data"``) or GCS URIs (``"gs://bucket/data"``).

    An ``embedding_model`` is required. To use Vertex AI embeddings, construct a
    ``VertexAIEmbedding`` with your own client and pass it here — Guava helpers
    never create API clients on your behalf.

    Example::

        from google import genai
        client = genai.Client(vertexai=True, project="my-project", location="us-central1")
        store = LanceDBStore("gs://my-bucket/lancedb", embedding_model=VertexAIEmbedding(client=client))

    Args:
        path: Local path or GCS URI for LanceDB storage.
        table_name: Name of the LanceDB table.
        embedding_model: Embedding model to use.
    """

    def __init__(
        self,
        path: str = "./lancedb_data",
        table_name: str = "chunks",
        *,
        embedding_model: EmbeddingModel,
    ):
        try:
            import lancedb as _lancedb  # ty: ignore[unresolved-import]
        except ImportError:
            raise ImportError(
                "lancedb is not installed. Run: pip install 'gridspace-guava[lancedb]'"
            ) from None
        self._embedding_model = embedding_model
        self._table_name = table_name
        self._db = _lancedb.connect(path)
        self._table = None
        if table_name in self._db.table_names():
            table = self._db.open_table(table_name)
            # Drop tables created before chunk_id column was added so they are
            # re-indexed automatically (DocumentQA re-ingests when count() == 0).
            if "chunk_id" not in table.schema.names:
                self._db.drop_table(table_name)
            else:
                self._table = table

    def add_texts(self, texts: list[str]) -> list[str]:
        ids = [str(uuid.uuid4()) for _ in texts]
        vectors = self._embedding_model.embed_documents(texts)
        t0 = time.perf_counter()
        data = [{"chunk_id": uid, "text": t, "vector": v} for uid, t, v in zip(ids, texts, vectors)]
        if self._table is None:
            self._table = self._db.create_table(self._table_name, data=data)
        else:
            self._table.add(data)
        logger.info("lancedb write: %d chunk(s) in %.3fs", len(texts), time.perf_counter() - t0)
        return ids

    def upsert_texts(self, ids: list[str], texts: list[str]) -> None:
        vectors = self._embedding_model.embed_documents(texts)
        data = [{"chunk_id": uid, "text": t, "vector": v} for uid, t, v in zip(ids, texts, vectors)]
        if self._table is None:
            self._table = self._db.create_table(self._table_name, data=data)
        else:
            (
                self._table.merge_insert("chunk_id")
                .when_matched_update_all()
                .when_not_matched_insert_all()
                .execute(data)
            )

    def delete(self, ids: list[str]) -> None:
        if self._table is None or not ids:
            return
        quoted = ", ".join(f"'{i}'" for i in ids)
        self._table.delete(f"chunk_id IN ({quoted})")

    def search(self, query: str, k: int = 5) -> list[str]:
        if self._table is None:
            return []
        vector = self._embedding_model.embed_query(query)
        t0 = time.perf_counter()
        results = self._table.search(vector).limit(k).to_list()
        logger.info("lancedb search: top-%d in %.3fs", k, time.perf_counter() - t0)
        return [row["text"] for row in results]

    def clear(self) -> None:
        if self._table is not None:
            self._db.drop_table(self._table_name)
            self._table = None

    def count(self) -> int:
        if self._table is None:
            return 0
        return self._table.count_rows()
