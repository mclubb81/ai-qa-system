# qa-verifier

An independent verification service for the `ai-qa-system` agentic pipeline.
It models each pipeline stage's output as a typed object and each agent's
transformation as a morphism between them, and checks two things on every
run:

- **Structural/composition contracts** (`src/laws.rs`): does the composite
  Planner -> Analyzer contract hold for every analyzed test case (it was
  actually planned; it has recorded step evidence)?
- **Independent correctness oracle** (`src/oracle.rs`): a functor `F` maps
  raw `StepResult` evidence to an expected verdict (any failing step implies
  `fail`, otherwise `pass`). A mismatch between the Analyzer's self-reported
  verdict and `F`'s image is flagged, with the correct verdict attached.

See `src/category.rs` for the underlying `Morphism`/`compose`/`Identity`
abstractions these checks are built from.

## Running

```sh
cd verifier
cargo run            # listens on 127.0.0.1:8787 by default
PORT=9000 cargo run   # override the port
```

## API

- `GET /healthz` -> `{"status": "ok"}`
- `POST /verify` with a JSON body `{run_id, test_plan, test_results}`
  (mirroring the Python pipeline's `QAState` shapes) -> a `VerificationReport`:

```json
{
  "consistent": false,
  "violations": [
    {
      "law": "functor_consistency",
      "scope": "tc-2",
      "severity": "error",
      "message": "Analyzer verdict 'pass' is inconsistent with step evidence (expected 'fail')",
      "corrected_verdict": "fail"
    }
  ],
  "checked_at": "2026-11-03T10:01:06Z"
}
```

See `tests/fixtures/sample_verify_request.json` /
`sample_verify_response.json` for a worked example (also used by the Python
pipeline's mocked tests, so the two sides can't silently drift apart).

## Testing

```sh
cargo test
```

All tests are pure unit/property tests against in-process fixtures -- no
network calls, no external process, no API keys required.
