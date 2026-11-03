# Dynamic Prompts (Postgres)

[← back to README](../README.md)

Every LLM-calling agent node (Planner, Executor, Analyzer, Triage, Codegen -- Healer reuses
Executor's and Codegen's) has a hardcoded default system prompt in `src/qa_agent/prompts/*.py`.
This page covers the **optional** layer on top: versioned, Postgres-backed prompt overrides that
can be edited via the CLI/web UI, or by an external program (e.g. a remote reinforcement-learning
loop). Entirely optional -- leave the prompts DB unconfigured and every node runs exactly as
before, using its hardcoded default.

## Why this exists

The hardcoded prompts are a fine starting point, but improving them by hand doesn't scale, and
this machine has no GPU/TPU to run a reinforcement-learning loop that improves them automatically.
That training runs remotely (e.g. on Google Colab or Kaggle). This feature makes prompts a piece of
*data* the pipeline reads at run time, rather than code, so a remote process can propose new
versions without a code change or deploy here.

## Schema

Lives in the same `qa_config` Postgres database as [`ConfigService`](logging-and-config.md) (a
separate table, not a third database) -- Postgres grants are per-table, so a narrowly-scoped
external role (see [below](#how-an-external-rl-program-reads-writes-this)) can be granted access
to just this table without touching `qa_config`'s own key/value rows (which may hold provider API
keys).

```sql
CREATE TABLE prompt_versions (
    id          BIGSERIAL PRIMARY KEY,
    node_name   TEXT NOT NULL,
    version     INTEGER NOT NULL,
    content     TEXT NOT NULL,
    source      TEXT NOT NULL DEFAULT 'manual',
    created_by  TEXT,
    metadata    JSONB,
    is_active   BOOLEAN NOT NULL DEFAULT false,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (node_name, version)
);
-- At most one active version per node, enforced without a second table.
CREATE UNIQUE INDEX prompt_versions_one_active_idx ON prompt_versions(node_name) WHERE is_active;
```

History is **append-only**: creating a new version, activating an older one, or reverting to the
hardcoded default never deletes a row, only flips `is_active`. `source` distinguishes who/what
wrote a version (e.g. `"manual"` vs `"rl"`) -- the dedicated-table equivalent of
`llm_router/state_store.py`'s `_router_state/` reserved-key-prefix convention for machine-written
data living alongside human-edited data.

Two attribution columns are also added to the existing `qa_logs` tables (see
[docs/logging-and-config.md](logging-and-config.md)), so any consumer can join a run's outcome to
the prompt versions that produced it:
- `llm_calls.prompt_version INTEGER`, `llm_calls.prompt_source_node TEXT` -- the latter exists
  because Healer logs under `node_name="healer"` but actually reuses the Executor's or Codegen's
  prompt numbering; without it you can't tell which node's version-space a healer row's
  `prompt_version` belongs to.
- `runs.prompt_versions JSONB` -- a `{node_name: version}` snapshot of every prompted node's active
  version at the start of that run (`null` for a node still on its hardcoded default).

## `PromptService` contract

```python
class PromptService:
    enabled: bool  # connection is not None

    @classmethod
    def from_settings(cls, settings=None) -> "PromptService": ...  # opens a sync connection,
                                                                      # ensures schema automatically

    def get_active_version(self, node_name: str, default: str) -> tuple[str, int | None]: ...
    def list_versions(self, node_name: str) -> list[PromptVersionRecord]: ...
    def create_version(self, node_name, content, *, source="manual", created_by=None,
                        metadata=None, activate=True) -> int: ...
    def activate(self, node_name: str, version: int) -> None: ...
    def revert_to_default(self, node_name: str) -> None: ...
```

Same dependency-injection pattern as `ConfigService`: `enabled` is the single source of truth,
`get_active_version`/`list_versions` never raise (fall back to `default`/`[]` on any failure --
including the DB simply being unconfigured), and the mutating methods (`create_version`,
`activate`, `revert_to_default`) raise `RuntimeError` when disabled, since each is an explicit
write triggered by a human (CLI/web) or an external program.

## How prompts reach the pipeline

`graph/build.py::build_graph` resolves all 5 nodes' active prompts **once per run** (one
`get_active_version` call per node), not inside each node's hot path -- the same tradeoff
`get_effective_settings()` makes by being deliberately uncached: a prompt change (via CLI, web UI,
or an external write) is visible on the very next run without restarting this process, with no
added DB latency inside the graph traversal itself. The resolved `(content, version)` pair is
passed into each node factory and threaded through to `ModelRouter.call_with_selection(...,
prompt_version=..., prompt_source_node=...)`, which `logged_llm_call` writes into `llm_calls`.

## CLI reference

See [docs/cli.md](cli.md#qa-agent-prompts-list) for the full flag tables. Quick reference:

```bash
qa-agent prompts list                              # every node's active version (or "default")
qa-agent prompts list planner                      # planner's full version history
qa-agent prompts show planner                      # active content
qa-agent prompts show planner --version 2           # a specific past version
qa-agent prompts set planner "New planner prompt..." # creates + activates version N+1
qa-agent prompts set planner ./draft.txt --no-activate
qa-agent prompts activate planner 2
qa-agent prompts revert planner                      # back to the hardcoded default
```

## Web UI

`qa-agent web` exposes a **Prompts** page alongside **Config**:
- `/prompts` -- a card per node: name, active version (or "default"), a short preview.
- `/prompts/<node>` -- full active content, a form to submit a new version (pre-filled with the
  current content, "activate immediately" checkbox), a version-history table with per-row
  "Activate" buttons, and a "Revert to hardcoded default" button.

Same disabled-service banner pattern as `/config` when `QA_CONFIG_DATABASE_URL` isn't set.

## How an external RL program reads/writes this

The managed Postgres project this app already uses for `qa_config`/`qa_logs` (e.g.
[Neon](https://neon.tech)) is reachable over the internet with SSL -- that's the integration
surface. An external program (e.g. a notebook running on Google Colab or Kaggle, which has the
GPU/TPU this machine doesn't) connects **directly to that same Postgres project**, with its own
credentials, to:
1. Read training signal from `runs`/`llm_calls` (outcomes, timing, and the `prompt_version`/
   `prompt_source_node`/`prompt_versions` attribution columns above).
2. Write a new row into `prompt_versions` (`source='rl'`, with whatever reward/training metadata
   it wants in `metadata`) to propose an improved prompt.

No new HTTP API, authentication layer, or tunnel is needed on this machine for this -- the local
Flask web UI stays loopback-only exactly as documented in [docs/web.md](web.md).

**Set this up with a separate, narrowly-scoped Postgres role** for the external program -- never
reuse this app's own `QA_CONFIG_DATABASE_URL`/`QA_LOGS_DATABASE_URL` credentials. In your managed
Postgres console:
- Grant `SELECT` only on `runs` and `llm_calls` -- **not** `qa_config` itself, whose rows may hold
  provider API keys as JSON values, and not `errors`/`node_events` unless you need them.
- Grant `SELECT, INSERT` (not `UPDATE`) on `prompt_versions` by default. This lets the external
  program propose new versions (`source='rl'`) while a human (or a separate, deliberate promotion
  step) decides what actually goes active, enforced purely by withholding the `UPDATE` grant. If
  you want the external program to auto-promote its own versions, that's an explicit escalation:
  grant column-level `UPDATE (is_active)` on `prompt_versions` instead.

This repo intentionally stops here: the RL algorithm itself, any notebook, and any reward-function
computation are out of scope -- only the raw, joinable per-call/per-run data and the versioned
prompt store are provided.

## Test coverage

- `tests/test_prompt_service.py` -- hand-rolled stubs (`_StubSyncConnection`, extended in
  `tests/conftest.py` with `prompt_versions`-shaped SQL branches alongside `ConfigService`'s),
  following the repo's no-mocking-framework convention.
- `tests/test_planner_node.py`, `test_analyzer_node.py`, `test_triage_node.py`,
  `test_codegen_node.py`, `test_executor_node.py` -- each node factory threading a custom
  `system_prompt` through to the actual LLM call.
- `tests/test_log_service.py` -- `prompt_version`/`prompt_source_node`/`prompt_versions`
  round-tripping through `log_llm_call`/`log_run_start`.
- `tests/test_cli_prompts.py` -- the `prompts list/show/set/activate/revert` commands against a
  stub `PromptService`.
- `tests/test_db_integration.py` -- `@pytest.mark.integration`, a real round-trip against live
  Postgres; skipped by default.
