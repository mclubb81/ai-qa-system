import asyncio
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from qa_agent.agents.healer import heal_many
from qa_agent.config import get_effective_settings, get_settings
from qa_agent.core.session import RunResult, run_qa_session
from qa_agent.db.client import get_config_dsn, get_logs_pool, get_sync_connection
from qa_agent.db.config_service import ConfigService
from qa_agent.db.log_service import LogService
from qa_agent.db.schema import ensure_config_schema, ensure_logs_schema
from qa_agent.llm_router.model_router import ModelRouter
from qa_agent.rag.client import get_qdrant_client
from qa_agent.rag.collections import ensure_collection
from qa_agent.rag.ingest import load_bug_records, load_doc_chunks
from qa_agent.rag.service import RagService
from qa_agent.utils.coerce import coerce_value

app = typer.Typer(add_completion=False)
console = Console()

config_app = typer.Typer(add_completion=False)
app.add_typer(config_app, name="config")


@app.callback()
def _main() -> None:
    """AI-powered QA agent, orchestrated with LangGraph + Playwright MCP."""
    # Having a callback (even a no-op one) keeps Typer in subcommand mode,
    # so `qa-agent run ...` stays required instead of collapsing to a flat
    # single-command CLI as it would with only one @app.command().


def _load_requirements(requirements: str) -> str:
    path = Path(requirements)
    if path.is_file():
        return path.read_text()
    return requirements


def _print_summary(result: RunResult) -> None:
    table = Table(title=f"QA Run {result.run_id} -- {result.overall_status.upper()}")
    table.add_column("Test Case")
    table.add_column("Priority")
    table.add_column("Verdict")

    for r in result.test_results:
        table.add_row(f"{r.test_case_id}: {r.title}", r.priority, r.verdict or "pending")

    console.print(table)

    if result.bugs:
        console.print(f"\n[bold red]{len(result.bugs)} bug(s) flagged:[/bold red]")
        for bug in result.bugs:
            suffix = f" (repro: {bug.repro_script_path})" if bug.repro_script_path else ""
            console.print(f"  - {bug.id} [{bug.severity}] {bug.title}{suffix}")

    if result.generated_scripts:
        console.print(f"\n[bold green]{len(result.generated_scripts)} regression script(s) generated:[/bold green]")
        for script in result.generated_scripts:
            console.print(f"  - {script.test_case_id}: {script.script_path}")

    console.print(f"\nMarkdown report: {result.report_markdown_path}")
    console.print(f"JSON report:     {result.report_json_path}")


@app.command()
def run(
    url: str = typer.Option(..., "--url", help="Target URL to test."),
    requirements: str = typer.Option(
        ..., "--requirements", help="Natural-language requirements, or a path to a file containing them."
    ),
    provider: str | None = typer.Option(
        None, "--provider", help="LLM provider: groq (default), google, anthropic, or openai."
    ),
    model: str | None = typer.Option(None, "--model", help="Override the provider's default model."),
    headless: bool | None = typer.Option(
        None, "--headless/--no-headless", help="Run the browser headless (default: from config/settings)."
    ),
    max_retries: int | None = typer.Option(
        None, "--max-retries", help="Retries for test cases judged 'flaky' (default: from config/settings)."
    ),
    reports_dir: Path | None = typer.Option(
        None, "--reports-dir", help="Directory to write reports into (default: from config/settings)."
    ),
    generate_regression_scripts: bool | None = typer.Option(
        None,
        "--generate-regression-scripts/--no-generate-regression-scripts",
        help="Generate a standalone Playwright regression script for every passing "
        "test case (default: from config/settings).",
    ),
    verbose: bool = typer.Option(False, "-v", "--verbose", help="Verbose output."),
) -> None:
    """Run an AI-powered QA session against a target URL."""
    req_text = _load_requirements(requirements)

    # CLI flags win when explicitly passed; otherwise fall back to the
    # config DB (if reachable) or .env/hardcoded defaults -- same
    # precedence as provider/model already had.
    settings = get_effective_settings()
    effective_headless = headless if headless is not None else settings.playwright_headless
    effective_max_retries = max_retries if max_retries is not None else settings.max_retries
    effective_reports_dir = reports_dir if reports_dir is not None else Path(settings.reports_dir)
    effective_generate_regression_scripts = (
        generate_regression_scripts
        if generate_regression_scripts is not None
        else settings.generate_regression_scripts
    )

    if verbose:
        console.print(f"[dim]Target: {url}[/dim]")
        console.print(f"[dim]Provider: {provider or '(default)'}[/dim]")

    result = asyncio.run(
        run_qa_session(
            target_url=url,
            requirements=req_text,
            provider=provider,
            model=model,
            headless=effective_headless,
            max_retries=effective_max_retries,
            reports_dir=effective_reports_dir,
            generate_regression_scripts=effective_generate_regression_scripts,
        )
    )
    _print_summary(result)
    raise typer.Exit(0 if result.overall_status == "pass" else 1)


@app.command("heal")
def heal(
    script: Path | None = typer.Option(
        None, "--script", help="Path to one generated_tests/<id>.py script to heal."
    ),
    all_: bool = typer.Option(
        False, "--all", help="Heal every generated script found under --reports-dir."
    ),
    reports_dir: Path | None = typer.Option(
        None, "--reports-dir", help="Where to scan for generated scripts (default: from config/settings)."
    ),
    provider: str | None = typer.Option(None, "--provider", help="LLM provider override for healing."),
    model: str | None = typer.Option(None, "--model", help="Model override for healing."),
) -> None:
    """Re-execute a generated regression script's original steps against the
    live app and, if it still passes, re-synthesize its locators from a
    fresh accessibility-tree snapshot. Does not require the original run's
    state -- reads the script's JSON sidecar instead, so this can be run
    long after (and independent of) the `qa-agent run` that produced it."""
    if script is None and not all_:
        console.print("[red]Specify --script <path> or --all.[/red]")
        raise typer.Exit(1)

    settings = get_effective_settings()
    effective_reports_dir = reports_dir if reports_dir is not None else Path(settings.reports_dir)
    targets = (
        [script]
        if script is not None
        else sorted(effective_reports_dir.glob(f"*/{settings.generated_tests_dirname}/*.py"))
    )
    if not targets:
        console.print("[yellow]No generated scripts found.[/yellow]")
        raise typer.Exit(0)

    router = ModelRouter.from_settings(settings, provider=provider, model=model)
    log_service = LogService.from_settings(settings)

    results = asyncio.run(heal_many(targets, router, log_service, settings))

    exit_code = 0
    status_colors = {"healed": "green", "still_valid": "dim", "regression_detected": "red"}
    for result in results:
        color = status_colors[result.status]
        console.print(f"[{color}]{result.status}: {result.script_path}[/{color}] -- {result.detail}")
        if result.status == "regression_detected":
            exit_code = 1
    raise typer.Exit(exit_code)


@app.command("ingest-docs")
def ingest_docs(
    path: Path = typer.Argument(..., help="A .md/.txt file, or a directory of them, to index."),
    chunk_size: int = typer.Option(1000, "--chunk-size", help="Max characters per chunk."),
    chunk_overlap: int = typer.Option(100, "--chunk-overlap", help="Overlap between consecutive chunks."),
) -> None:
    """Ingest product docs into the qa_docs Qdrant collection for the Planner to retrieve from."""
    settings = get_effective_settings()
    rag_service = RagService.from_settings(settings)
    if not rag_service.enabled:
        console.print(
            "[red]RAG is not configured -- set QDRANT_URL, QDRANT_API_KEY, and GOOGLE_API_KEY in .env.[/red]"
        )
        raise typer.Exit(1)

    client = get_qdrant_client(settings)
    assert client is not None, "rag_service.enabled already confirmed Qdrant is configured"
    ensure_collection(client, settings.qdrant_docs_collection)

    chunks = load_doc_chunks(path, chunk_size=chunk_size, overlap=chunk_overlap)
    count = rag_service.upsert_docs(chunks)
    console.print(f"Ingested {count} chunk(s) into '{settings.qdrant_docs_collection}'.")


@app.command("ingest-bugs")
def ingest_bugs(
    path: Path = typer.Argument(
        ..., help="A JSON file: a list of {id?, title, description, severity?} records."
    ),
) -> None:
    """Seed the qa_bugs Qdrant collection for Triage's known-issue lookup."""
    settings = get_effective_settings()
    rag_service = RagService.from_settings(settings)
    if not rag_service.enabled:
        console.print(
            "[red]RAG is not configured -- set QDRANT_URL, QDRANT_API_KEY, and GOOGLE_API_KEY in .env.[/red]"
        )
        raise typer.Exit(1)

    client = get_qdrant_client(settings)
    assert client is not None, "rag_service.enabled already confirmed Qdrant is configured"
    ensure_collection(client, settings.qdrant_bugs_collection)

    bugs = load_bug_records(path)
    count = rag_service.upsert_bugs(bugs)
    console.print(f"Ingested {count} bug(s) into '{settings.qdrant_bugs_collection}'.")


@config_app.command("set")
def config_set(
    key: str = typer.Argument(..., help="Setting name, must match a Settings field (e.g. max_retries)."),
    value: str = typer.Argument(..., help="Value to store -- parsed as JSON if possible, else as a string."),
) -> None:
    """Set a config value in the qa_config DB (stored as JSON)."""
    service = ConfigService.from_settings(get_settings())
    if not service.enabled:
        console.print("[red]Config DB is not configured -- set QA_CONFIG_DATABASE_URL in .env.[/red]")
        raise typer.Exit(1)
    service.set(key, coerce_value(value))
    console.print(f"Set {key!r} = {value!r}")


@config_app.command("get")
def config_get(key: str = typer.Argument(..., help="Setting name to look up.")) -> None:
    """Get a config value from the qa_config DB."""
    service = ConfigService.from_settings(get_settings())
    value = service.get(key)
    if value is None:
        console.print(f"[yellow]{key!r} is not set (falls back to .env/default).[/yellow]")
        raise typer.Exit(1)
    console.print(value)


@config_app.command("list")
def config_list() -> None:
    """List every config value currently stored in the qa_config DB."""
    service = ConfigService.from_settings(get_settings())
    if not service.enabled:
        console.print("[yellow]Config DB is not configured -- set QA_CONFIG_DATABASE_URL in .env.[/yellow]")
        raise typer.Exit(1)
    values = service.get_all()
    if not values:
        console.print("[dim](no config values set -- everything falls back to .env/defaults)[/dim]")
        return
    for key, value in values.items():
        console.print(f"{key} = {value}")


@app.command("db-init")
def db_init() -> None:
    """Explicitly (re-)create the qa_logs/qa_config schemas.

    Not required for normal use -- ConfigService/LogService ensure their
    own schema automatically on first connect -- but useful for decoupling
    ops/CI setup from a first `qa-agent run`/`config set`.
    """
    settings = get_settings()

    config_dsn = get_config_dsn(settings)
    if config_dsn:
        conn = get_sync_connection(config_dsn)
        if conn is not None:
            ensure_config_schema(conn)
            conn.close()
            console.print("qa_config schema ensured.")
        else:
            console.print("[red]Could not connect to qa_config DB.[/red]")
    else:
        console.print("[dim]QA_CONFIG_DATABASE_URL not set -- skipping qa_config.[/dim]")

    logs_pool = get_logs_pool(settings)
    if logs_pool is not None:
        asyncio.run(_ensure_logs_schema_once(logs_pool))
        console.print("qa_logs schema ensured.")
    else:
        console.print("[dim]QA_LOGS_DATABASE_URL not set -- skipping qa_logs.[/dim]")


async def _ensure_logs_schema_once(pool) -> None:
    await pool.open(wait=True, timeout=5)
    await ensure_logs_schema(pool)
    await pool.close()


@app.command("web")
def web(
    host: str = typer.Option("127.0.0.1", "--host", help="Interface to bind (default: localhost-only)."),
    port: int = typer.Option(5000, "--port", help="Port to listen on."),
    debug: bool = typer.Option(False, "--debug", help="Enable Flask debug mode (reload + debugger)."),
) -> None:
    """Launch the local web UI (run sessions, browse reports, edit config, trigger heal)."""
    try:
        from qa_agent.web.app import create_app
    except ImportError:
        console.print("[red]Flask is not installed -- run `pip install -e \".[web]\"`.[/red]")
        raise typer.Exit(1) from None

    if debug and host not in ("127.0.0.1", "localhost"):
        console.print(
            "[red]Refusing --debug with a non-localhost --host (Werkzeug's debugger allows "
            "arbitrary code execution if reachable).[/red]"
        )
        raise typer.Exit(1)

    console.print(f"Serving on http://{host}:{port} (Ctrl+C to stop)")
    create_app().run(host=host, port=port, debug=debug)


if __name__ == "__main__":
    app()
