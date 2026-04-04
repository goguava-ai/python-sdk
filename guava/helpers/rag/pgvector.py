import uuid

import numpy as np

from .embedding import EmbeddingModel
from .vectorstore import VectorStore


class PgVectorStore(VectorStore):
    """Vector store backed by PostgreSQL with pgvector.

    Requires a PostgreSQL database with the ``vector`` extension available.

    An ``embedding_model`` is required. To use Vertex AI embeddings, construct a
    ``VertexAIEmbedding`` with your own client and pass it here — Guava helpers
    never create API clients on your behalf.

    Args:
        db_url: PostgreSQL connection string.
        table_name: Name of the table to store chunks in.
        embedding_model: Embedding model to use.
    """

    def __init__(
        self,
        db_url: str,
        table_name: str = "guava_chunks",
        *,
        embedding_model: EmbeddingModel,
    ):
        import psycopg  # ty: ignore[unresolved-import]
        from pgvector.psycopg import register_vector  # ty: ignore[unresolved-import]

        self._embedding_model = embedding_model
        self._table_name = table_name
        self._conn = psycopg.connect(db_url, autocommit=True)
        self._ensure_table()
        register_vector(self._conn)

    def _ensure_table(self) -> None:
        dim = self._embedding_model.ndims()
        with self._conn.cursor() as cur:
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
            cur.execute(
                f"CREATE TABLE IF NOT EXISTS {self._table_name} "
                f"(id SERIAL PRIMARY KEY, chunk_id TEXT UNIQUE, content TEXT, embedding vector({dim}))"
            )
            # Auto-migrate tables created before chunk_id was added.
            cur.execute(f"ALTER TABLE {self._table_name} ADD COLUMN IF NOT EXISTS chunk_id TEXT")
            cur.execute(
                f"CREATE UNIQUE INDEX IF NOT EXISTS {self._table_name}_chunk_id_idx "
                f"ON {self._table_name} (chunk_id)"
            )
            cur.execute(
                f"CREATE INDEX IF NOT EXISTS {self._table_name}_embedding_idx "
                f"ON {self._table_name} USING hnsw (embedding vector_cosine_ops)"
            )

    def _to_arrays(self, vectors: list[list[float]]) -> list[np.ndarray]:
        return [np.array(v, dtype=np.float32) for v in vectors]

    def add_texts(self, texts: list[str]) -> list[str]:
        ids = [str(uuid.uuid4()) for _ in texts]
        vectors = self._to_arrays(self._embedding_model.embed_documents(texts))
        with self._conn.cursor() as cur:
            cur.executemany(
                f"INSERT INTO {self._table_name} (chunk_id, content, embedding) VALUES (%s, %s, %s)",
                [(uid, t, v) for uid, t, v in zip(ids, texts, vectors)],
            )
        return ids

    def upsert_texts(self, ids: list[str], texts: list[str]) -> None:
        vectors = self._to_arrays(self._embedding_model.embed_documents(texts))
        with self._conn.cursor() as cur:
            cur.executemany(
                f"INSERT INTO {self._table_name} (chunk_id, content, embedding) VALUES (%s, %s, %s) "
                f"ON CONFLICT (chunk_id) DO UPDATE SET content = EXCLUDED.content, embedding = EXCLUDED.embedding",
                [(uid, t, v) for uid, t, v in zip(ids, texts, vectors)],
            )

    def delete(self, ids: list[str]) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                f"DELETE FROM {self._table_name} WHERE chunk_id = ANY(%s)",
                (ids,),
            )

    def search(self, query: str, k: int = 5) -> list[str]:
        vector = np.array(self._embedding_model.embed_query(query), dtype=np.float32)
        with self._conn.cursor() as cur:
            cur.execute(
                f"SELECT content FROM {self._table_name} ORDER BY embedding <=> %s LIMIT %s",
                (vector, k),
            )
            return [row[0] for row in cur.fetchall()]

    def clear(self) -> None:
        with self._conn.cursor() as cur:
            cur.execute(f"DELETE FROM {self._table_name}")

    def count(self) -> int:
        with self._conn.cursor() as cur:
            cur.execute(f"SELECT COUNT(*) FROM {self._table_name}")
            return cur.fetchone()[0]
