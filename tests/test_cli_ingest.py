from pathlib import Path

from typer.testing import CliRunner

import qa_agent.cli as cli_module
from qa_agent.cli import app

runner = CliRunner()


class _StubRagService:
    def __init__(self, enabled=True):
        self.enabled = enabled
        self.docs_upserted = None
        self.bugs_upserted = None

    def upsert_docs(self, chunks):
        self.docs_upserted = chunks
        return len(chunks)

    def upsert_bugs(self, bugs):
        self.bugs_upserted = bugs
        return len(bugs)


def _patch_rag(monkeypatch, stub):
    monkeypatch.setattr(cli_module.RagService, "from_settings", classmethod(lambda cls, settings=None: stub))
    monkeypatch.setattr(cli_module, "ensure_collection", lambda client, name: None)
    monkeypatch.setattr(cli_module, "get_qdrant_client", lambda settings: object())


def test_ingest_docs_reports_chunk_count(monkeypatch):
    stub = _StubRagService(enabled=True)
    _patch_rag(monkeypatch, stub)

    docs_dir = Path(__file__).parent / "fixtures" / "docs"
    result = runner.invoke(app, ["ingest-docs", str(docs_dir)])

    assert result.exit_code == 0
    assert stub.docs_upserted
    assert "Ingested" in result.stdout


def test_ingest_bugs_reports_bug_count(monkeypatch):
    stub = _StubRagService(enabled=True)
    _patch_rag(monkeypatch, stub)

    bugs_path = Path(__file__).parent / "fixtures" / "bugs" / "sample_bugs.json"
    result = runner.invoke(app, ["ingest-bugs", str(bugs_path)])

    assert result.exit_code == 0
    assert stub.bugs_upserted is not None
    assert len(stub.bugs_upserted) == 2


def test_ingest_docs_fails_clearly_when_rag_disabled(monkeypatch):
    stub = _StubRagService(enabled=False)
    monkeypatch.setattr(cli_module.RagService, "from_settings", classmethod(lambda cls, settings=None: stub))

    docs_dir = Path(__file__).parent / "fixtures" / "docs"
    result = runner.invoke(app, ["ingest-docs", str(docs_dir)])

    assert result.exit_code == 1
    assert "not configured" in result.stdout


def test_ingest_bugs_fails_clearly_when_rag_disabled(monkeypatch):
    stub = _StubRagService(enabled=False)
    monkeypatch.setattr(cli_module.RagService, "from_settings", classmethod(lambda cls, settings=None: stub))

    bugs_path = Path(__file__).parent / "fixtures" / "bugs" / "sample_bugs.json"
    result = runner.invoke(app, ["ingest-bugs", str(bugs_path)])

    assert result.exit_code == 1
    assert "not configured" in result.stdout
