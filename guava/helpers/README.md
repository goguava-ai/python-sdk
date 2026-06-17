# Guava Helpers Module

The `guava.helpers` module provides high-level abstractions for Retrieval-Augmented Generation (RAG), vector storage, intent classification, datetime parsing, and real-time server communication. The LLM-backed helpers (`IntentRecognizer`, `DatetimeFilter`, `DateRangeParser`) call the Guava server using only a `GUAVA_API_KEY` — no third-party LLM credentials needed. RAG vector-store and embedding/generation helpers (`pinecone`, `chromadb`, `lancedb`, `pgvector`, `genai`, `openai`) require their own credentials by nature.

> **Migration note:** The Gemini RAG wrappers previously named `VertexAIEmbedding` / `VertexAIGeneration` in `helpers/vertexai.py` are now `GenAIEmbedding` / `GenAIGeneration` in `helpers/genai.py`. The old names continue to import from `helpers.vertexai` for one release (with a `DeprecationWarning`); switch to `from guava.helpers.genai import GenAIEmbedding, GenAIGeneration` to silence the warning. The deprecated LLM-style classes (`IntentRecognizer`, `DateRangeParser`, `DatetimeFilter` in `helpers/genai.py`; `IntentRecognizer`, `IntentClarifier`, `DatetimeFilter`, the old file-search `DocumentQA` in `helpers/openai.py`) and the `helpers/beta.py` factory remain for one more release — each emits a `DeprecationWarning` on construction. Migrate intent/datetime helpers to `helpers/llm.py` (Guava-key path), or to the new RAG wrappers for direct Gemini/OpenAI use. The new RAG wrappers in `helpers/openai.py` and `helpers/genai.py` do not warn.

## Table of Contents

- [Module Overview](#module-overview)
- [System Diagrams](#system-diagrams)
  - [LLM Helper Architecture](#0-llm-helper-architecture)
  - [Document Q&A System](#1-document-qa-system)
  - [Vector Store Layer](#2-vector-store-layer)
  - [Cloud Model Integrations (RAG only)](#3-cloud-model-integrations-rag-only)
  - [Intent & Datetime Processing](#4-intent--datetime-processing)
  - [Server Communication](#5-server-communication)
- [Design Principles](#design-principles)

---

## Module Overview

| File | Purpose |
|---|---|
| `rag.py` | Abstract base classes (`VectorStore`, `EmbeddingModel`, `GenerationModel`), `chunk_document()`, and the `DocumentQA` orchestrator |
| `server_rag.py` | HTTP client for Guava server-side RAG API |
| `chromadb.py` | ChromaDB vector store implementation |
| `lancedb.py` | LanceDB vector store (local or GCS) |
| `pgvector.py` | PostgreSQL pgvector vector store |
| `pinecone.py` | Pinecone serverless vector store + Pinecone Inference embedding |
| `genai.py` | Google Gemini (Vertex AI or AI Studio) embedding and generation models for RAG (`GenAIEmbedding`, `GenAIGeneration`); also contains the deprecated LLM-style `IntentRecognizer` / `DateRangeParser` / `DatetimeFilter` for one more release |
| `openai.py` | OpenAI embedding and generation models for RAG (`OpenAIEmbedding`, `OpenAIGeneration`); also contains the deprecated LLM-style `IntentRecognizer` / `IntentClarifier` / `DatetimeFilter` / file-search `DocumentQA` for one more release |
| `beta.py` | Deprecated factory `create_openai_client()` that proxies through the Guava server; kept while the deprecated `openai.py` classes still depend on it |
| `vertexai.py` | Backward-compatibility shim re-exporting `GenAIEmbedding`/`GenAIGeneration` under the legacy `VertexAI*` names; emits a `DeprecationWarning` on use |
| `llm.py` | LLM-backed helper classes (`IntentRecognizer`, `DatetimeFilter`, `DateRangeParser`) — calls the Guava server `POST /v1/llm/generate` endpoint |
| `fastapi.py` | FastAPI WebSocket router for Guava call controllers |

---


## System Diagrams

### 0. LLM Helper Architecture

The LLM-backed helpers (`IntentRecognizer`, `DatetimeFilter`, `DateRangeParser`) call the Guava server's `POST /v1/llm/generate` endpoint directly. Only a `GUAVA_API_KEY` is required.

```
  ┌─────────────────────────────────────────┐
  │  Helper classes (llm.py)                │
  │                                         │
  │  IntentRecognizer  ── classify()        │
  │  DatetimeFilter    ── filter()          │
  │  DateRangeParser   ── parse()           │
  └────────────────┬────────────────────────┘
                   │
                   v
          Guava Server
          POST /v1/llm/generate
```

```python
from guava.helpers.llm import IntentRecognizer

ir = IntentRecognizer(["billing", "support", "sales"])
ir.classify("I need help with my bill")
```

If you want to drive a third-party LLM directly from inside Guava callbacks (e.g. to use your own OpenAI / Gemini key, model, or fine-tune), see the `examples/integrations/openai` and `examples/integrations/genai` directories in the [guava-starter](https://github.com/gridspace/guava-starter) repo.

### 1. Document Q&A System

The central RAG orchestration system. `DocumentQA` in `rag.py` supports two operational modes — server-side and local — with a unified API.

```
                         +---------------------------+
                         |       DocumentQA          |
                         |       (rag.py)            |
                         +---------------------------+
                         |  upsert_document()        |
                         |  add_document()           |
                         |  delete_document()        |
                         |  ask(question, k)         |
                         +-------------+-------------+
                                       |
                          mode selection (store=None?)
                         /                            \
                        v                              v
          +-------------------+          +----------------------------+
          |   Server Mode     |          |       Local Mode           |
          | (store is None)   |          |  (store + generation_model)|
          +-------------------+          +----------------------------+
          |                   |          |                            |
          v                   |          v                            v
  +--------------+            |  +---------------+       +------------------+
  |  ServerRAG   |            |  | VectorStore   |       | GenerationModel  |
  | (server_     |            |  | (abstract)    |       | (abstract)       |
  |  rag.py)     |            |  +-------+-------+       +--------+---------+
  +--------------+            |          |                         |
  | HTTP API     |            |          |   (see Vector Store     |   (see Cloud Model
  | POST/DELETE/ |            |          |    Layer below)          |    Integrations)
  | GET/ASK      |            |          |                         |
  +--------------+            |  +-------+-------+       +---------+---------+
          |                   |  | chunk_document |       |                   |
          v                   |  | (paragraph-    |       |  Implementations: |
  +---------------+           |  |  boundary      |       |  GenAI            |
  | Guava Server  |           |  |  splitting)    |       |  Generation       |
  | RAG API       |           |  +----------------+       +-------------------+
  +---------------+           |
                              |
                  +-----------+-----------+
                  | Content Addressing    |
                  | SHA256 hash keys      |
                  | Namespace scoping     |
                  | Reconciliation logic  |
                  +-----------------------+
```

#### Indexing flow (local mode)

```
  documents: list[str]
         |
         v
  ┌─ chunk_document(doc, chunk_size=5000, overlap=200) ───────────────────┐
  │                                                                        │
  │  1. Split text on paragraph boundaries ("\n\n")                        │
  │  2. Group paragraphs until chunk_size chars reached                    │
  │  3. When overlap > 0, carry last paragraph into next chunk             │
  │                                                                        │
  │  Example (3 paragraphs, 2 chunks):                                     │
  │    chunk_1 = "para_1\n\npara_2"                                        │
  │    chunk_2 = "para_2\n\npara_3"   ← para_2 overlaps for context        │
  └────────────┬───────────────────────────────────────────────────────────┘
               |
               v
  ┌─ VectorStore.add_texts(chunks) or .upsert_texts(ids, chunks) ─────────┐
  │                                                                        │
  │  Internally calls EmbeddingModel.embed_documents(chunks)               │
  │    → e.g. GenAIEmbedding: gemini-embedding-001                         │
  │      task_type = RETRIEVAL_DOCUMENT (optimized for indexing)            │
  │      (OpenAIEmbedding is task-agnostic — same call for docs and query) │
  │    → returns list[list[float]] (one vector per chunk)                   │
  │                                                                        │
  │  Stores (chunk_id, text, vector) in the chosen backend                 │
  │                                                                        │
  │  When ids are provided:                                                │
  │    chunk_ids = ["{doc_key}:0", "{doc_key}:1", ...]                     │
  │    → deterministic, enabling upsert/delete by document key             │
  └────────────────────────────────────────────────────────────────────────┘
```

#### Query flow (local mode) — DocumentQA.ask()

```
  question: "What is my deductible?"
         |
         v
  ┌─ VectorStore.search(question, k=5) ──────────────────────────────────┐
  │                                                                       │
  │  1. EmbeddingModel.embed_query(question)                              │
  │     → e.g. GenAIEmbedding: gemini-embedding-001                       │
  │       task_type = QUESTION_ANSWERING (optimized for retrieval)         │
  │     → single vector (768-dim Gemini, 1536-dim OpenAI, 1024 Pinecone)  │
  │                                                                       │
  │  2. Cosine similarity search against stored chunk vectors              │
  │     → returns top-k chunk texts as list[str]                          │
  └───────────┬───────────────────────────────────────────────────────────┘
              |
              v
  ┌─ GenerationModel.generate() ──────────────────────────────────────────┐
  │                                                                       │
  │  System instruction (configurable via instructions= param):           │
  │  ┌─────────────────────────────────────────────────────────────┐      │
  │  │ "You are a virtual agent. Your task is to answer questions   │      │
  │  │  using ONLY the provided supporting document excerpts.       │      │
  │  │  If the answer is not in the provided context, say so.       │      │
  │  │  Just answer the question — do not offer any follow-ups."    │      │
  │  └─────────────────────────────────────────────────────────────┘      │
  │                                                                       │
  │  Prompt:                                                              │
  │  ┌─────────────────────────────────────────────────────────────┐      │
  │  │ Context:                                                     │      │
  │  │ {chunk_1}                                                    │      │
  │  │                                                              │      │
  │  │ ---                                                          │      │
  │  │                                                              │      │
  │  │ {chunk_2}                                                    │      │
  │  │                                                              │      │
  │  │ ---                                                          │      │
  │  │                                                              │      │
  │  │ {chunk_3}                                                    │      │
  │  │                                                              │      │
  │  │ Question: What is my deductible?                             │      │
  │  └─────────────────────────────────────────────────────────────┘      │
  │                                                                       │
  │  Output: free-text answer (no JSON schema)                            │
  │  → e.g. GenAIGeneration calls Gemini 2.5 Flash,                       │
  │         OpenAIGeneration calls gpt-5-mini                             │
  └───────────┬───────────────────────────────────────────────────────────┘
              |
              v
        returns answer string
```

### 2. Vector Store Layer

Four interchangeable implementations behind the `VectorStore` abstract interface.

```
                          +-------------------+
                          |    VectorStore    |
                          |    (abstract)     |
                          +-------------------+
                          | add_texts()       |
                          | upsert_texts()    |
                          | delete()          |
                          | search()          |
                          | clear()           |
                          | count()           |
                          +---------+---------+
                                    |
            +-----------+-----------+-----------+-----------+
            |           |                       |           |
            v           v                       v           v
  +-----------+  +-----------+          +-----------+  +-----------+
  | ChromaDB  |  | LanceDB   |          | pgvector  |  | Pinecone  |
  | Vector    |  | Store     |          | Store     |  | Vector    |
  | Store     |  |           |          |           |  | Store     |
  +-----------+  +-----------+          +-----------+  +-----------+
  | chromadb  |  | lancedb   |          | psycopg   |  | pinecone  |
  | library   |  | library   |          | pgvector  |  | library   |
  +-----------+  +-----------+          +-----------+  +-----------+
  | Built-in  |  | Requires  |          | Requires  |  | Built-in  |
  | MiniLM    |  | external  |          | external  |  | Pinecone  |
  | embedding |  | Embedding |          | Embedding |  | Inference |
  |    OR     |  | Model     |          | Model     |  | embedding |
  | custom    |  |           |          |           |  |    OR     |
  | Embedding |  |           |          |           |  | custom    |
  | Model     |  |           |          |           |  | Embedding |
  +-----------+  +-----------+          +-----------+  | Model     |
  | cosine    |  | local or  |          | HNSW      |  +-----------+
  | metric    |  | GCS       |          | index     |  | serverless|
  | local or  |  | (gs://)   |          | cosine    |  | cosine    |
  | in-memory |  | auto-     |          | auto-DDL  |  | auto-     |
  |           |  | migration |          |           |  | create    |
  +-----------+  +-----------+          +-----------+  | batch 100 |
                                                       +-----------+

         +-------------------+
         |  EmbeddingModel   |
         |  (abstract)       |
         +-------------------+
         | ndims()           |
         | embed()           |
         | embed_documents() |
         | embed_query()     |
         +---------+---------+
                   |
        +----------+----------+----------------+
        |                     |                |
        v                     v                v
  +--------------+  +------------------+  +--------------+
  | GenAI        |  | OpenAI           |  | Pinecone     |
  | Embedding    |  | Embedding        |  | Inference    |
  | (genai.py)   |  | (openai.py)      |  | Embedding    |
  +--------------+  +------------------+  | (pinecone.py)|
  | gemini-      |  | text-embedding-  |  +--------------+
  | embedding-001|  | 3-small          |  | multilingual-|
  | 768 dims     |  | 1536 dims        |  | e5-large     |
  | task-specific|  | task-agnostic    |  | 1024 dims    |
  | RETRIEVAL_DOC|  | dimensions=      |  | passage/     |
  | vs QUESTION  |  | param            |  | query input  |
  +--------------+  +------------------+  +--------------+
```

### 3. Cloud Model Integrations (RAG only)

Integration adapters for Google Gemini and OpenAI, used as embedding and generation models for the local-mode RAG path. The caller supplies the configured client; Guava helpers never instantiate clients on your behalf.

```
  +---------------------------+        +---------------------------+
  |    Google Gemini          |        |        OpenAI             |
  |    (genai.py)             |        |       (openai.py)         |
  +---------------------------+        +---------------------------+
  |                           |        |                           |
  |  GenAIEmbedding           |        |  OpenAIEmbedding          |
  |    embed_documents()      |        |    embed_documents()      |
  |    embed_query()          |        |    embed_query()          |
  |                           |        |                           |
  |  GenAIGeneration          |        |  OpenAIGeneration         |
  |    generate()             |        |    generate()             |
  +-------------+-------------+        +-------------+-------------+
                |                                    |
                v                                    v
        google.genai.Client                  openai.OpenAI
        (Vertex AI or AI Studio)             (chat.completions / embeddings)
```

### 4. Intent & Datetime Processing

All prompt construction, JSON-schema generation, and response parsing for the three LLM-backed helpers (`IntentRecognizer`, `DatetimeFilter`, `DateRangeParser`) lives in `llm.py`. Each helper sends its prompt to the Guava server's `POST /v1/llm/generate` endpoint via httpx.

#### IntentRecognizer — ranked plausible matches

Matches a user intent string against a fixed set of choices and returns all plausible matches as `SuggestedAction` objects, ordered by likelihood. Returns `None` if no choice plausibly matches. Use `result[0]` for the single best match, or return the list from `on_action_request` to let the dialog engine disambiguate.

```
  User intent: "something about my deductible"
  Choices: {"auto": "Car insurance, collision, ...",
            "home": "Homeowners, dwelling, ...",
            "life": "Term life, whole life, ..."}
                |
                v
  ┌─ IntentRecognizer.classify() ──────────────────────────────────────────┐
  │                                                                        │
  │  1. CONSTRUCT PROMPT                                                   │
  │     ┌────────────────────────────────────────────────────────────┐     │
  │     │ Analyze the given intent and identify which choices from   │     │
  │     │ the list could potentially match.                          │     │
  │     │                                                            │     │
  │     │ Intent: "something about my deductible"                    │     │
  │     │ Available Choices: ["auto", "home", "life"]                │     │
  │     │                                                            │     │
  │     │ Rules:                                                     │     │
  │     │ - If the intent clearly matches ONE choice, return only    │     │
  │     │   that choice                                              │     │
  │     │ - If the intent could match MULTIPLE choices, return all   │     │
  │     │   plausible matches (ordered by likelihood)                │     │
  │     │ - If the intent does NOT match any, return an empty list   │     │
  │     │                                                            │     │
  │     │ Detailed descriptions of each choice:                      │     │
  │     │   auto: Car insurance, collision, ...                      │     │
  │     │   home: Homeowners, dwelling, ...                          │     │
  │     │   life: Term life, whole life, ...                         │     │
  │     └────────────────────────────────────────────────────────────┘     │
  │     (descriptions block only included when intent_choices is a dict)   │
  │                                                                        │
  │  2. BUILD JSON SCHEMA (Pydantic create_model at __init__ time)         │
  │     ┌────────────────────────────────────────────────────────────┐     │
  │     │ {                                                          │     │
  │     │   "possible_matches": list[Literal["auto","home","life"]], │     │
  │     │   "reasoning": str | null                                  │     │
  │     │ }                                                          │     │
  │     │ extra = "forbid"                                           │     │
  │     └────────────────────────────────────────────────────────────┘     │
  │                                                                        │
  │  3. LLM CALL                                                           │
  │     backend.generate(prompt, json_schema=schema)                       │
  │                                                                        │
  │  4. PARSE + WRAP AS SuggestedAction                                    │
  │     json.loads(response)["possible_matches"] → ["auto", "home"]        │
  │     → [SuggestedAction(key="auto", description="Car insurance, ..."),  │
  │        SuggestedAction(key="home", description="Homeowners, ...")]     │
  │     (reasoning field is discarded — used only to improve LLM output)   │
  └────────────┬───────────────────────────────────────────────────────────┘
               │
               v
         returns [SuggestedAction("auto", ...), SuggestedAction("home", ...)]
```

#### DateRangeParser — natural language to date range

Converts natural language time expressions ("next Tuesday", "this weekend", "next week") into concrete `(start_date, end_date)` bounds. Adds a configurable buffer on each side and clamps to [today, today+365].

```
  User query: "next Tuesday"
  Today: 2026-04-20 (Monday)
                |
                v
  ┌─ DateRangeParser.parse(query, buffer_days=1) ─────────────────────────┐
  │                                                                        │
  │  1. CONSTRUCT PROMPT                                                   │
  │     ┌────────────────────────────────────────────────────────────┐     │
  │     │ Extract the date or date range the user is asking about.   │     │
  │     │ If the query mentions a specific day, start_date and       │     │
  │     │ end_date should both be that day.                          │     │
  │     │ If the query mentions a range like "next week", use the    │     │
  │     │ full range.                                                │     │
  │     │ Dates must be between 2026-04-20 and 2027-04-20.           │     │
  │     │ If the query doesn't contain a clear date, default to      │     │
  │     │ the next 7 days.                                           │     │
  │     │                                                            │     │
  │     │ Query: "next Tuesday"                                      │     │
  │     │ Today's date: 2026-04-20 (Monday)                          │     │
  │     └────────────────────────────────────────────────────────────┘     │
  │                                                                        │
  │  2. JSON SCHEMA (Pydantic _DateRangeModel)                             │
  │     ┌────────────────────────────────────────────────────────────┐     │
  │     │ {                                                          │     │
  │     │   "start_date": date,  // "first date, inclusive"          │     │
  │     │   "end_date":   date   // "last date, inclusive"           │     │
  │     │ }                                                          │     │
  │     └────────────────────────────────────────────────────────────┘     │
  │                                                                        │
  │  3. LLM CALL                                                           │
  │     backend.generate(prompt, json_schema=schema)                       │
  │     → LLM returns: {"start_date":"2026-04-21","end_date":"2026-04-21"} │
  │                                                                        │
  │  4. VALIDATE + POST-PROCESS                                            │
  │     _DateRangeModel.model_validate_json(response)                      │
  │     → apply buffer: start - 1 day, end + 1 day                         │
  │     → clamp to [today, today+365]                                      │
  │     → (2026-04-20, 2026-04-22)                                         │
  └────────────┬───────────────────────────────────────────────────────────┘
               │
               v
         returns (date(2026-04-20), date(2026-04-22))
```

#### DatetimeFilter — match slots by natural language

Filters a pre-loaded list of ISO-8601 datetime slots against a natural language query. Returns both matching slots and close alternatives as fallbacks.

```
  Query: "Tuesday afternoon"
  Today: April 20, 2026
  Available slots:
    2026-04-21T09:00, 2026-04-21T10:00, 2026-04-21T14:00,
    2026-04-21T15:00, 2026-04-22T09:00, 2026-04-22T14:00
                |
                v
  ┌─ DatetimeFilter.filter(query, max_results=5) ─────────────────────────┐
  │                                                                        │
  │  1. CONSTRUCT PROMPT                                                   │
  │     ┌────────────────────────────────────────────────────────────┐     │
  │     │ Return datetime slots from the list that match the query.  │     │
  │     │ If none match, return close alternatives in                │     │
  │     │ other_appointments instead.                                │     │
  │     │ Never return datetimes that are not in the list.           │     │
  │     │                                                            │     │
  │     │ Query: Tuesday afternoon                                   │     │
  │     │ Today's Date: April 20, 2026                               │     │
  │     │ Available slots:                                           │     │
  │     │ 2026-04-21T09:00                                           │     │
  │     │ 2026-04-21T10:00                                           │     │
  │     │ 2026-04-21T14:00                                           │     │
  │     │ 2026-04-21T15:00                                           │     │
  │     │ 2026-04-22T09:00                                           │     │
  │     │ 2026-04-22T14:00                                           │     │
  │     │                                                            │     │
  │     │ Return at most 5 items per list.                           │     │
  │     └────────────────────────────────────────────────────────────┘     │
  │                                                                        │
  │  2. JSON SCHEMA (Pydantic _FilterModel)                                │
  │     ┌────────────────────────────────────────────────────────────┐     │
  │     │ {                                                          │     │
  │     │   "matching_appointments": list[str],                      │     │
  │     │   "other_appointments":    list[str]                       │     │
  │     │ }                                                          │     │
  │     └────────────────────────────────────────────────────────────┘     │
  │                                                                        │
  │  3. LLM CALL                                                           │
  │     backend.generate(prompt, json_schema=schema)                       │
  │                                                                        │
  │  4. VALIDATE + TRUNCATE                                                │
  │     _FilterModel.model_validate_json(response)                         │
  │     → matching[:max_results], fallback[:max_results]                   │
  └────────────┬───────────────────────────────────────────────────────────┘
               │
               v
         returns (
           ["2026-04-21T14:00", "2026-04-21T15:00"],     # matching
           ["2026-04-22T14:00", "2026-04-21T09:00", ...] # fallbacks
         )
```

#### Composing helpers in a scheduling pipeline

The three helpers can be chained to fully enrich a raw user utterance into a structured scheduling action:

```
  "I want to book next Tuesday afternoon"
                |
                v
  IntentRecognizer.classify(["schedule","cancel","reschedule","view"])
    → [SuggestedAction("schedule", ...)]   (or pick result[0] for the best)
                |
                v
  DateRangeParser.parse("next Tuesday afternoon", buffer_days=1)
    → (2026-04-20, 2026-04-22)
                |
                v   (use date range to filter available slots from calendar)
  DatetimeFilter.filter("afternoon", max_results=5)
    → matching:  ["2026-04-21T14:00", "2026-04-21T15:00"]
      fallbacks: ["2026-04-22T14:00"]
                |
                v
  Enriched result:
    intent    = "schedule"
    dates     = Apr 20–22
    slots     = 2 matches + 1 fallback
    → ready for booking system
```

#### Transport layer

All three helpers call the Guava server via httpx:

```
  helper builds prompt + JSON schema
                |
                v
        POST /v1/llm/generate
                |
                v
          Guava Server
```

### 5. Server Communication

Real-time WebSocket integration for Guava call controllers via FastAPI.

```
  External Caller (Guava Server)
            |
            | WebSocket + Bearer Token
            v
  +---------------------------+
  |   FastAPI WebSocket       |
  |   Router (fastapi.py)     |
  +---------------------------+
  | create_router(            |
  |   controller_class,       |
  |   inbound_token,          |
  |   path="/inbound-call"    |
  | )                         |
  +---------------------------+
            |
            | 1. Authenticate (constant-time compare)
            | 2. Accept WebSocket
            | 3. Instantiate CallController
            |
            v
  +---------------------------+
  |    Concurrent Loops       |
  +---------------------------+
  |                           |
  |  +---------------------+  |
  |  | process_events()    |  |     Inbound: WebSocket -> Controller
  |  | Receive JSON events |  |
  |  | Deserialize Event   |  |     Each event spawns a thread:
  |  | Spawn thread:       |  |       controller.on_event(event)
  |  |   on_event(event)   |  |
  |  +---------------------+  |
  |                           |
  |  +---------------------+  |
  |  | process_commands()  |  |     Outbound: Controller -> WebSocket
  |  | Drain command queue |  |
  |  | Serialize Command   |  |     controller._command_queue
  |  | Send via WebSocket  |  |       -> JSON -> WebSocket
  |  +---------------------+  |
  |                           |
  +---------------------------+
            |
            | On disconnect
            v
  controller.shutdown()
```

### Full System Interaction Map

How all subsystems connect at the highest level:

```
  +===========================================================================+
  ||                         GUAVA HELPERS MODULE                            ||
  +===========================================================================+
  |                                                                           |
  |  +---------------------+          +----------------------------------+    |
  |  |   DocumentQA        |          |   LLM Helpers (llm.py)          |    |
  |  |   (rag.py)          |          |   IntentRecognizer               |    |
  |  +---------------------+          |   DatetimeFilter                 |    |
  |  |  Server   |  Local  |          |   DateRangeParser                |    |
  |  |  Mode     |  Mode   |          |                                  |    |
  |  +-----+-----+----+----+          +-----------------+----------------+    |
  |        |          |                                 |                     |
  |        v          v                                 v                     |
  |  +-----------+ +-------+                  POST /v1/llm/generate           |
  |  | ServerRAG | |VecStr |                                                  |
  |  | (server_  | |       |       +--------+ +-------+ +-------+ +--------+  |
  |  |  rag.py)  | +---+---+       |ChromaDB| |LanceDB| |pgvec  | |Pinecone|  |
  |  +-----+-----+     |           +--------+ +-------+ +-------+ +--------+  |
  |        |           +-----------------+                                    |
  |        v                             |                                    |
  |  +---------+                         v                                    |
  |  | Guava   | <----------------------(text storage / vector search)        |
  |  | Server  |                                                              |
  |  +---------+                                                              |
  |                                                                           |
  |  +----------------------------+    +-------------------------------+      |
  |  | Embedding & Generation     |    | Server Communication          |      |
  |  +----------------------------+    +-------------------------------+      |
  |  | genai.py:                  |    | fastapi.py:                   |      |
  |  |   GenAIEmbedding           |    |   create_router()             |      |
  |  |   GenAIGeneration          |    |   WebSocket event/command     |      |
  |  | openai.py:                 |    |   processing                  |      |
  |  |   OpenAIEmbedding          |    +-------------------------------+      |
  |  |   OpenAIGeneration         |                                           |
  |  | pinecone.py:               |                                           |
  |  |   PineconeInference        |                                           |
  |  |   Embedding                |                                           |
  |  +----------------------------+                                           |
  |                                                                           |
  |  vertexai.py is a backward-compatibility shim re-exporting the genai      |
  |  classes under the legacy VertexAI* names — see the migration note above. |
  +===========================================================================+
```

---

## Files

### `rag.py`

Core RAG abstractions and the main `DocumentQA` orchestrator.

#### Abstract Base Classes

**`VectorStore`** — Unified interface for embedding and retrieving text chunks.

| Method | Signature | Description |
|---|---|---|
| `add_texts` | `(texts: list[str]) -> list[str]` | Embed and store texts, return opaque IDs |
| `upsert_texts` | `(ids: list[str], texts: list[str]) -> None` | Add or replace chunks by ID |
| `delete` | `(ids: list[str]) -> None` | Remove chunks by ID |
| `search` | `(query: str, k: int = 5) -> list[str]` | Retrieve top-k similar chunks |
| `clear` | `() -> None` | Remove all data |
| `count` | `() -> int` | Return chunk count |

**`EmbeddingModel`** — Pluggable text-to-vector conversion.

| Method | Signature | Description |
|---|---|---|
| `ndims` | `() -> int` | Vector dimensionality |
| `embed` | `(texts: list[str]) -> list[list[float]]` | Embed a batch of texts |
| `embed_documents` | `(texts: list[str]) -> list[list[float]]` | Task-specific document embedding (defaults to `embed()`) |
| `embed_query` | `(text: str) -> list[float]` | Task-specific query embedding (defaults to `embed([text])[0]`) |

**`GenerationModel`** — QA text generation.

| Method | Signature | Description |
|---|---|---|
| `generate` | `(prompt: str, *, system_instruction: str \| None = None) -> str` | Generate a response |

#### Utility Functions

**`chunk_document(document, chunk_size=5000, overlap=200) -> list[str]`** — Splits documents into overlapping chunks on paragraph boundaries. Groups paragraphs until `chunk_size` characters are reached. The last paragraph of each chunk carries forward to the next when `overlap > 0`, preserving cross-boundary context.

#### `DocumentQA` Class

The main orchestrator for Q&A over documents. Operates in two modes:

- **Server mode** (default): Delegates to Guava server-side RAG API via `ServerRAG`. No local vector store or API credentials needed.
- **Local mode**: Caller provides a configured `VectorStore` and `GenerationModel` for full control.

| Parameter | Type | Description |
|---|---|---|
| `store` | `VectorStore \| None` | Vector store (None triggers server mode) |
| `documents` | `list[str] \| str \| None` | Bulk-load documents at construction |
| `ids` | `list[str] \| None` | Explicit document IDs for upsert/delete |
| `chunk_size` | `int` | Local mode chunk size (default 5000) |
| `chunk_overlap` | `int` | Local mode overlap (default 200) |
| `instructions` | `str \| None` | System instruction override |
| `generation_model` | `GenerationModel \| None` | Required in local mode |
| `server_rag` | `ServerRAG \| None` | Explicit ServerRAG instance |
| `namespace` | `str \| None` | Namespace for server-side document scoping |

| Method | Description |
|---|---|
| `upsert_document(key, text)` | Add or replace a document by key |
| `add_document(text)` | Add a document (content-addressed in server mode) |
| `delete_document(key)` | Delete a document by key |
| `clear()` | Remove all documents |
| `ask(question, k=5)` | Retrieve relevant chunks and generate an answer |

---

### `server_rag.py`

HTTP client for Guava's server-side RAG API. Handles document lifecycle, namespace scoping, and state reconciliation.

**`ServerRAG` Class**

| Parameter | Type | Description |
|---|---|---|
| `base_url` | `str` | Guava server base URL |
| `api_key` | `str` | Bearer token for authentication |
| `namespace` | `str \| None` | Key prefix for multi-instance scoping |

| Method | Description |
|---|---|
| `reconcile(documents, ids)` | Sync server state — skip existing content-addressed docs, delete stale ones |
| `upsert_document(key, text)` | Upload or replace a document by key |
| `add_document(text)` | Upload with a content-derived key (SHA256 hash) |
| `delete_document(key)` | Delete a document by key |
| `clear()` | Delete all tracked documents |
| `ask(question, instructions)` | Ask a question against tracked documents |

**API Endpoints Used:**
- `POST v1/rag/documents` — Upload document
- `DELETE v1/rag/documents/{key}` — Delete document
- `GET v1/rag/documents` — List documents
- `POST v1/rag/ask` — Ask question

---

### `chromadb.py`

ChromaDB vector store with optional custom embedding model.

**`ChromaVectorStore` Class** — Implements `VectorStore`.

| Parameter | Type | Description |
|---|---|---|
| `path` | `str \| None` | Persistent storage path (default `./chroma_data`, None for in-memory) |
| `collection_name` | `str` | ChromaDB collection name (default `"chunks"`) |
| `embedding_model` | `EmbeddingModel \| None` | Custom embedder (defaults to built-in all-MiniLM-L6-v2) |

Uses cosine similarity metric. Auto-generates sequential string IDs for `add_texts()`.

---

### `lancedb.py`

LanceDB vector store supporting local paths and GCS URIs.

**`LanceDBStore` Class** — Implements `VectorStore`.

| Parameter | Type | Description |
|---|---|---|
| `path` | `str` | Local path or GCS URI (`gs://bucket/data`), default `./lancedb_data` |
| `table_name` | `str` | LanceDB table name (default `"chunks"`) |
| `embedding_model` | `EmbeddingModel` | Required — no built-in embedding |

Uses UUID-based IDs. Automatically migrates tables with outdated schemas (drops tables missing `chunk_id` column).

---

### `pgvector.py`

PostgreSQL pgvector vector store with HNSW indexing.

**`PgVectorStore` Class** — Implements `VectorStore`.

| Parameter | Type | Description |
|---|---|---|
| `db_url` | `str` | PostgreSQL connection string |
| `table_name` | `str` | Table name (default `"guava_chunks"`) |
| `embedding_model` | `EmbeddingModel` | Required — no built-in embedding |

Schema: `id (SERIAL PK)`, `chunk_id (TEXT UNIQUE)`, `content (TEXT)`, `embedding (vector(dim))`. Auto-creates the pgvector extension, table, and HNSW index. Uses `INSERT ... ON CONFLICT` for upserts.

---

### `pinecone.py`

Pinecone serverless vector store with built-in Pinecone Inference embedding.

**`PineconeInferenceEmbedding` Class** — Implements `EmbeddingModel`.

| Parameter | Type | Description |
|---|---|---|
| `pc` | `Pinecone` | Pinecone client instance |
| `model` | `str` | Inference model (default `"multilingual-e5-large"`) |
| `dimensionality` | `int` | Output dimensions (default 1024) |

Uses different `input_type` values for documents (`"passage"`) vs. queries (`"query"`).

**`PineconeVectorStore` Class** — Implements `VectorStore`.

| Parameter | Type | Description |
|---|---|---|
| `api_key` | `str \| None` | API key (falls back to `PINECONE_API_KEY` env var) |
| `index_name` | `str` | Index name (default `"guava-chunks"`) |
| `cloud` | `str` | Cloud provider (default `"aws"`) |
| `region` | `str` | Serverless region (default `"us-east-1"`) |
| `embedding_model` | `EmbeddingModel \| None` | Custom embedder (defaults to `PineconeInferenceEmbedding`) |

Auto-creates serverless index if missing. Batch upserts in 100-vector chunks. Stores text in vector metadata.

---

### `genai.py`

Google Gemini embedding and generation model implementations for the local-mode RAG path. Works with either a Vertex AI client (`genai.Client(vertexai=True, ...)`) or an AI Studio client (`genai.Client(api_key=...)`).

Install with `pip install 'guava-sdk[genai]'` (or install `google-genai>=1.55.0` directly).

**`GenAIEmbedding` Class** — Implements `EmbeddingModel`.

| Parameter | Type | Description |
|---|---|---|
| `client` | `google.genai.Client` | Configured Gemini client (caller-supplied) |
| `model` | `str` | Embedding model (default `"gemini-embedding-001"`) |
| `dimensionality` | `int` | Output dimensions (default 768) |

Uses task type `RETRIEVAL_DOCUMENT` for document embedding and `QUESTION_ANSWERING` for query embedding.

**`GenAIGeneration` Class** — Implements `GenerationModel`.

| Parameter | Type | Description |
|---|---|---|
| `client` | `google.genai.Client` | Configured Gemini client (caller-supplied) |
| `model` | `str` | Generation model (default `"gemini-2.5-flash"`) |
| `thinking_budget` | `int \| None` | Token budget for the model's internal thinking step. Default `0` disables thinking on `gemini-2.5-flash` for faster responses. Pass `None` for non-thinking models (e.g. `gemini-1.5-flash`); pass a positive integer to enable extended thinking. |

#### Deprecated legacy LLM helpers (same module)

For one more release, `helpers/genai.py` also exports the older Gemini-backed LLM helpers. Each emits a `DeprecationWarning` on construction. Migrate to `guava.helpers.llm` (Guava-key path); if you specifically want to drive Gemini yourself, call `google.genai` directly inside your callback.

| Class | Replacement |
|---|---|
| `IntentRecognizer(intent_choices, client)` | `guava.helpers.llm.IntentRecognizer` |
| `DateRangeParser(client, model=...)` | `guava.helpers.llm.DateRangeParser` |
| `DatetimeFilter(source_list, client, model=...)` | `guava.helpers.llm.DatetimeFilter` |

---

### `openai.py`

OpenAI embedding and generation model implementations for the local-mode RAG path. Caller supplies a configured `openai.OpenAI` client (which works equally well against Azure OpenAI or any OpenAI-compatible base URL).

Install with `pip install 'guava-sdk[openai]'` (or install `openai>=2.8.1` directly).

**`OpenAIEmbedding` Class** — Implements `EmbeddingModel`.

| Parameter | Type | Description |
|---|---|---|
| `client` | `openai.OpenAI` | Configured OpenAI client (caller-supplied) |
| `model` | `str` | Embedding model (default `"text-embedding-3-small"`) |
| `dimensionality` | `int` | Output dimensions (default 1536). Sent as the `dimensions=` parameter for every model except `text-embedding-ada-002`, which rejects it. |

Task-agnostic — `embed_documents` and `embed_query` share a single underlying call (OpenAI has no document/query task distinction).

**`OpenAIGeneration` Class** — Implements `GenerationModel`.

| Parameter | Type | Description |
|---|---|---|
| `client` | `openai.OpenAI` | Configured OpenAI client (caller-supplied) |
| `model` | `str` | Chat model (default `"gpt-5-mini"`) |

Calls `chat.completions.create`. The `system_instruction` argument maps to a `system` message prepended to the `user` prompt.

#### Deprecated legacy LLM helpers (same module)

For one more release, `helpers/openai.py` also exports the older OpenAI-backed LLM helpers. Each emits a `DeprecationWarning` on construction. Migrate to `guava.helpers.llm` (Guava-key path) or to `guava.helpers.rag.DocumentQA` + `OpenAIGeneration` above.

| Class | Replacement |
|---|---|
| `IntentRecognizer(intent_choices, client=None)` | `guava.helpers.llm.IntentRecognizer` |
| `IntentClarifier(intent_choices, client=None)` | `guava.helpers.llm.IntentRecognizer` (the new server-backed version returns ranked plausible matches) |
| `DatetimeFilter(source_list, client=None)` | `guava.helpers.llm.DatetimeFilter` |
| `DocumentQA(vector_store_name, document, client=None)` *(OpenAI file_search)* | `guava.helpers.rag.DocumentQA(store=..., generation_model=OpenAIGeneration(client=...))` |

When `client` is omitted, the legacy classes call `beta.create_openai_client()` to build an OpenAI client that proxies through the Guava server using `GUAVA_API_KEY`. That factory is itself deprecated.

---

### `beta.py` *(deprecated)*

`create_openai_client() -> openai.OpenAI` — returns an OpenAI client pointed at the Guava server's OpenAI proxy, using `GUAVA_API_KEY`. Emits a `DeprecationWarning` on call. Kept while the legacy classes in `openai.py` still depend on it; will be removed in the same release that removes those classes.

---

### `vertexai.py` *(compatibility shim)*

Backward-compatibility shim that re-exports `GenAIEmbedding` / `GenAIGeneration` under their legacy `VertexAIEmbedding` / `VertexAIGeneration` names. Each legacy name emits a single `DeprecationWarning` on first access, then caches the resolved class so subsequent lookups are silent.

The shim will be removed in a future release. Migrate to:

```python
from guava.helpers.genai import GenAIEmbedding, GenAIGeneration
```

---

### `llm.py`

LLM-backed helper classes. Each helper builds its prompt and Pydantic JSON schema, calls `POST /v1/llm/generate` on the Guava server via httpx, and parses the response. Requires only a `GUAVA_API_KEY`.

**`IntentRecognizer`** — Match user intent against a fixed set of choices, returning all plausible matches ordered by likelihood.

| Parameter | Type | Description |
|---|---|---|
| `intent_choices` | `list[str] \| dict[str, str]` | Choices or choice-to-description mapping |

| Method | Description |
|---|---|
| `classify(intent)` | Return `list[SuggestedAction]` ordered by likelihood, or `None` if no match. Use `result[0]` for the single best, or return the list from `on_action_request` to let the dialog engine disambiguate |

**`DatetimeFilter`** — Filter ISO-8601 datetime slots using natural language.

| Parameter | Type | Description |
|---|---|---|
| `source_list` | `list[str]` | Available ISO-8601 datetimes |

| Method | Description |
|---|---|
| `filter(query, max_results=5)` | Return `(matching, fallback)` tuple of datetime lists |

**`DateRangeParser`** — Parse natural language time expressions into concrete date ranges.

| Method | Description |
|---|---|
| `parse(query, buffer_days=1)` | Return `(start_date, end_date)` inclusive range, bounded to [today, today+365] |

---

### `fastapi.py`

FastAPI WebSocket router for real-time Guava call controllers.

**`create_router(controller_class, inbound_token, path="/inbound-call") -> APIRouter`**

Creates a WebSocket endpoint that:
1. Authenticates via Bearer token (constant-time comparison)
2. Instantiates the provided `CallController` subclass
3. Runs two concurrent loops: event processing (inbound) and command draining (outbound)
4. Calls `controller.shutdown()` on disconnect

---

## Design Principles

1. **One key, one path** — LLM-backed helpers (`IntentRecognizer`, `DatetimeFilter`, `DateRangeParser`) require only `GUAVA_API_KEY` and call the Guava server directly. If you want to drive a third-party LLM yourself, do so inline in your call controller — see `examples/integrations/openai` and `examples/integrations/genai` in guava-starter.

2. **Pluggable RAG backends** — `VectorStore`, `EmbeddingModel`, and `GenerationModel` are abstract base classes for the local-mode RAG path. Swap implementations without changing application code.

3. **Dual-mode RAG** — `DocumentQA` works in server mode (zero infrastructure) or local mode (full control) based on whether a `VectorStore` is provided.

4. **Content addressing** — Documents default to SHA256-based keys for idempotent uploads and automatic deduplication.

5. **Namespace scoping** — Server-side documents can be scoped by namespace, enabling multiple concurrent `DocumentQA` instances without collision.

6. **Task-specific embeddings** — Embedding models distinguish between document indexing and query embedding to improve retrieval quality.

7. **Graceful auto-migration** — Vector store implementations detect and migrate outdated schemas automatically.
