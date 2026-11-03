from dataclasses import dataclass

from typer.testing import CliRunner

import qa_agent.cli as cli_module
from qa_agent.cli import app

runner = CliRunner()


@dataclass
class _VersionRecord:
    node_name: str
    version: int
    content: str
    source: str
    created_by: str | None
    metadata: dict | None
    is_active: bool
    created_at: str


class _StubPromptService:
    def __init__(self, enabled=True, versions=None):
        self.enabled = enabled
        self._versions: dict[str, list[_VersionRecord]] = versions or {}
        self.create_calls = []
        self.activate_calls = []
        self.revert_calls = []

    def _active(self, node):
        return next((v for v in self._versions.get(node, []) if v.is_active), None)

    def get_active_version(self, node, default):
        active = self._active(node)
        if active is None:
            return default, None
        return active.content, active.version

    def list_versions(self, node):
        return list(self._versions.get(node, []))

    def create_version(self, node, content, *, source="manual", created_by=None, metadata=None, activate=True):
        if not self.enabled:
            raise RuntimeError("Prompts DB is not configured -- set QA_CONFIG_DATABASE_URL.")
        self.create_calls.append((node, content, source, activate))
        rows = self._versions.setdefault(node, [])
        new_version = max((v.version for v in rows), default=0) + 1
        if activate:
            for v in rows:
                v.is_active = False
        rows.append(
            _VersionRecord(node, new_version, content, source, created_by, metadata, activate, "2026-01-01T00:00:00Z")
        )
        return new_version

    def activate(self, node, version):
        if not self.enabled:
            raise RuntimeError("Prompts DB is not configured -- set QA_CONFIG_DATABASE_URL.")
        self.activate_calls.append((node, version))
        rows = self._versions.get(node, [])
        match = next((v for v in rows if v.version == version), None)
        if match is None:
            raise ValueError(f"No such prompt version: node={node!r} version={version!r}")
        for v in rows:
            v.is_active = False
        match.is_active = True

    def revert_to_default(self, node):
        if not self.enabled:
            raise RuntimeError("Prompts DB is not configured -- set QA_CONFIG_DATABASE_URL.")
        self.revert_calls.append(node)
        for v in self._versions.get(node, []):
            v.is_active = False


def _patch_prompts(monkeypatch, stub):
    monkeypatch.setattr(cli_module.PromptService, "from_settings", classmethod(lambda cls, settings=None: stub))


def test_prompts_set_creates_and_activates_by_default(monkeypatch):
    stub = _StubPromptService(enabled=True)
    _patch_prompts(monkeypatch, stub)

    result = runner.invoke(app, ["prompts", "set", "planner", "new planner prompt"])

    assert result.exit_code == 0
    assert stub.create_calls == [("planner", "new planner prompt", "manual", True)]
    assert "activated" in result.stdout


def test_prompts_set_no_activate_leaves_version_inactive(monkeypatch):
    stub = _StubPromptService(enabled=True)
    _patch_prompts(monkeypatch, stub)

    result = runner.invoke(app, ["prompts", "set", "planner", "draft", "--no-activate"])

    assert result.exit_code == 0
    assert stub.create_calls == [("planner", "draft", "manual", False)]
    assert "not activated" in result.stdout


def test_prompts_set_fails_clearly_when_disabled(monkeypatch):
    stub = _StubPromptService(enabled=False)
    _patch_prompts(monkeypatch, stub)

    result = runner.invoke(app, ["prompts", "set", "planner", "draft"])

    assert result.exit_code == 1
    assert "not configured" in result.stdout


def test_prompts_set_rejects_unknown_node(monkeypatch):
    stub = _StubPromptService(enabled=True)
    _patch_prompts(monkeypatch, stub)

    result = runner.invoke(app, ["prompts", "set", "bogus", "draft"])

    assert result.exit_code == 1
    assert "Unknown node" in result.stdout


def test_prompts_activate_happy_path(monkeypatch):
    stub = _StubPromptService(enabled=True)
    _patch_prompts(monkeypatch, stub)
    stub.create_version("planner", "v1")
    stub.create_version("planner", "v2")

    result = runner.invoke(app, ["prompts", "activate", "planner", "1"])

    assert result.exit_code == 0
    assert stub.activate_calls == [("planner", 1)]


def test_prompts_activate_unknown_version_errors(monkeypatch):
    stub = _StubPromptService(enabled=True)
    _patch_prompts(monkeypatch, stub)

    result = runner.invoke(app, ["prompts", "activate", "planner", "99"])

    assert result.exit_code == 1
    assert "No such prompt version" in result.stdout


def test_prompts_revert(monkeypatch):
    stub = _StubPromptService(enabled=True)
    _patch_prompts(monkeypatch, stub)
    stub.create_version("planner", "v1")

    result = runner.invoke(app, ["prompts", "revert", "planner"])

    assert result.exit_code == 0
    assert stub.revert_calls == ["planner"]
    assert "reverted" in result.stdout


def test_prompts_list_all_nodes_shows_default_when_none_active(monkeypatch):
    stub = _StubPromptService(enabled=True)
    _patch_prompts(monkeypatch, stub)

    result = runner.invoke(app, ["prompts", "list"])

    assert result.exit_code == 0
    assert "using hardcoded default" in result.stdout


def test_prompts_show_prints_active_content(monkeypatch):
    stub = _StubPromptService(enabled=True)
    _patch_prompts(monkeypatch, stub)
    stub.create_version("planner", "the active planner prompt")

    result = runner.invoke(app, ["prompts", "show", "planner"])

    assert result.exit_code == 0
    assert "the active planner prompt" in result.stdout
