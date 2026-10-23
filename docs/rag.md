# RAG (Retrieval-Augmented Generation)

[← back to README](../README.md)

Grounds the Planner in indexed product documentation, and lets Bug Triage look up similar
previously-known bugs, via [Qdrant](https://qdrant.tech/) + Google's free `text-embedding-004`
embeddings. **Entirely optional** -- every piece of this feature degrades silently to "no context"
when it isn't configured, and `qa-agent` behaves identically to a build with RAG never installed.

## Components

All under `src/qa_agent/rag/`:

| File | Responsibility |
|---|---|
| `client.py::get_qdrant_client` | Lazily builds a `QdrantClient`, `@lru_cache`'d on `(url, api_key)` (not on the `Settings` object, which isn't hashable). Returns `None` -- never raises -- if Qdrant isn't configured. |
| `embeddings.py::get_embeddings` | Lazily builds a `GoogleGenerativeAIEmbeddings` client, `@lru_cache`'d on `(model, api_key)`. Returns `None` if no Google API key is set. |
| `service.py::RagService` | The only thing other code should touch. Wraps the client + embeddings with graceful-degradation semantics (below). |
| `collections.py::ensure_collection` | Creates a Qdrant collection if missing. Only ever called from the CLI ingestion commands -- the read path (`retrieve_docs`/`find_similar_bugs`) never creates collections. |
| `chunking.py::chunk_text` | A simple sliding-window character chunker (default 1000 chars / 100 overlap). Deliberately not markdown-aware. |
| `ingest.py` | `load_doc_chunks` (globs `.md`/`.txt` under a path or a single file, chunks each) and `load_bug_records` (parses a JSON list of bug dicts). CLI-only helpers. |
| `models.py` | `RetrievedDoc` (`text`, `source`, `score`) and `SimilarBug` (`id`, `title`, `description`, `severity`, `score`). |

## The two Qdrant collections

| Collection | Vector config | Payload |
|---|---|---|
| `qa_docs` | 768-dim, cosine distance | `{text, source}` |
| `qa_bugs` | 768-dim, cosine distance | `{id, title, description, severity}` |

768 dimensions matches Google's `text-embedding-004` output size (`rag/collections.py::VECTOR_SIZE`).
Collection names are configurable via `QDRANT_DOCS_COLLECTION`/`QDRANT_BUGS_COLLECTION` (default
`qa_docs`/`qa_bugs`).

## Embedding model/provider

Google `text-embedding-004`, via `langchain_google_genai.GoogleGenerativeAIEmbeddings`. Reuses the
same `GOOGLE_API_KEY` as the `google` LLM provider -- you don't need a second key. Configurable via
`RAG_EMBEDDING_MODEL` if you ever need to swap models (note: changing it means recreating both
collections, since the vector size is baked in at creation time).

## `RagService` contract

```python
class RagService:
    enabled: bool  # client is not None and embeddings is not None

    @classmethod
    def from_settings(cls, settings=None) -> "RagService": ...

    async def retrieve_docs(self, query: str, top_k: int | None = None) -> list[RetrievedDoc]: ...
    async def find_similar_bugs(self, query: str, top_k: int | None = None) -> list[SimilarBug]: ...

    def upsert_docs(self, chunks: list[tuple[str, str]]) -> int: ...
    def upsert_bugs(self, bugs: list[dict]) -> int: ...
```

The core contract, worth preserving in any future change:

- **Reads never raise.** `retrieve_docs`/`find_similar_bugs` return `[]` if the service is
  `disabled`, and also return `[]` (after logging a warning) if the underlying Qdrant/embedding
  call fails -- including querying a collection that doesn't exist yet. This is deliberate: a
  retrieval failure must never interrupt a live QA run.
- **Writes raise when disabled.** `upsert_docs`/`upsert_bugs` raise `RuntimeError` if the service
  isn't configured. Ingestion is an explicit user action via the CLI, so a silent no-op there would
  be misleading rather than graceful.
- `top_k` defaults to `settings.rag_docs_top_k` (5) / `settings.rag_bugs_top_k` (3) when not passed.

## How the graph uses it

- **Retriever** (`agents/retriever.py`) runs once, first, in every session. Query:
  `f"{target_url}\n\n{requirements_raw}"`. Result lands in `state["retrieved_docs"]`, which the
  Planner folds into its prompt as a "Relevant product documentation (retrieved)" block.
- **Bug Triage** (`agents/triage.py`) calls `find_similar_bugs(f"{title}\n{reasoning}")` for the
  flagged result it's processing, folds the results into its prompt as a "Similar previously known
  bugs" block, and records the matched ids verbatim on the produced `Bug.similar_bug_refs` (not
  LLM-authored).

See [docs/architecture.md](architecture.md) for the full node lifecycle.

## Local setup

```bash
pip install -e ".[rag]"
```

1. Create a free [Qdrant Cloud](https://cloud.qdrant.io) cluster and grab its URL + API key.
2. In `.env`, set `QDRANT_URL`, `QDRANT_API_KEY`, and `GOOGLE_API_KEY` (same free key as the
   `google` LLM provider -- get one at https://aistudio.google.com/apikey).

`Settings.rag_enabled` (a computed property in `config.py`) is `True` only when all three of
`qdrant_url`, `qdrant_api_key`, and `google_api_key` are set -- `RagService.enabled` is the
runtime equivalent, checked after actually building the client/embeddings.

## CLI ingestion commands

```bash
qa-agent ingest-docs ./docs --chunk-size 1000 --chunk-overlap 100
qa-agent ingest-bugs ./known_bugs.json
```

- `ingest-docs PATH` -- `PATH` is a single `.md`/`.txt` file or a directory of them (globbed,
  sorted). Each file is chunked and upserted into `qa_docs`.
- `ingest-bugs PATH` -- `PATH` is a JSON file containing a list of `{id?, title, description,
  severity?}` records, upserted into `qa_bugs`.
- Both commands call `ensure_collection` before writing (creating the collection on first use) and
  exit with code `1` and a red error message if RAG isn't configured.

Full flag reference: [docs/cli.md](cli.md).

## Test coverage

- `tests/test_rag_service.py` -- `RagService` against hand-rolled `_StubQdrantClient`/
  `_StubEmbeddings` stubs (no mocking framework, consistent with the rest of the repo): happy path,
  disabled-service behavior, and simulated query/write failures.
- `tests/test_rag_integration.py` -- `@pytest.mark.integration`, a real round-trip against live
  Qdrant + Google embeddings; skipped by default (`pytest -m integration` with real credentials to
  run it).
- `tests/test_cli_ingest.py`, `tests/test_retriever_node.py`, `tests/test_triage_node.py` (its
  RAG-related assertions).
- `tests/fixtures/docs/sample.md` and `tests/fixtures/bugs/sample_bugs.json` -- example ingestion
  inputs used by the tests above.
