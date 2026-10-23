import asyncio
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from qa_agent.config import get_settings
from qa_agent.core.session import RunResult, run_qa_session
from qa_agent.rag.client import get_qdrant_client
from qa_agent.rag.collections import ensure_collection
from qa_agent.rag.ingest import load_bug_records, load_doc_chunks
from qa_agent.rag.service import RagService

app = typer.Typer(add_completion=False)
console = Console()


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
            console.print(f"  - {bug.id} [{bug.severity}] {bug.title}")

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
    headless: bool = typer.Option(True, "--headless/--no-headless", help="Run the browser headless."),
    max_retries: int = typer.Option(1, "--max-retries", help="Retries for test cases judged 'flaky'."),
    reports_dir: Path = typer.Option(Path("reports"), "--reports-dir", help="Directory to write reports into."),
    verbose: bool = typer.Option(False, "-v", "--verbose", help="Verbose output."),
) -> None:
    """Run an AI-powered QA session against a target URL."""
    req_text = _load_requirements(requirements)

    if verbose:
        console.print(f"[dim]Target: {url}[/dim]")
        console.print(f"[dim]Provider: {provider or '(default)'}[/dim]")

    result = asyncio.run(
        run_qa_session(
            target_url=url,
            requirements=req_text,
            provider=provider,
            model=model,
            headless=headless,
            max_retries=max_retries,
            reports_dir=reports_dir,
        )
    )
    _print_summary(result)
    raise typer.Exit(0 if result.overall_status == "pass" else 1)


@app.command("ingest-docs")
def ingest_docs(
    path: Path = typer.Argument(..., help="A .md/.txt file, or a directory of them, to index."),
    chunk_size: int = typer.Option(1000, "--chunk-size", help="Max characters per chunk."),
    chunk_overlap: int = typer.Option(100, "--chunk-overlap", help="Overlap between consecutive chunks."),
) -> None:
    """Ingest product docs into the qa_docs Qdrant collection for the Planner to retrieve from."""
    rag_service = RagService.from_settings()
    if not rag_service.enabled:
        console.print(
            "[red]RAG is not configured -- set QDRANT_URL, QDRANT_API_KEY, and GOOGLE_API_KEY in .env.[/red]"
        )
        raise typer.Exit(1)

    settings = get_settings()
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
    rag_service = RagService.from_settings()
    if not rag_service.enabled:
        console.print(
            "[red]RAG is not configured -- set QDRANT_URL, QDRANT_API_KEY, and GOOGLE_API_KEY in .env.[/red]"
        )
        raise typer.Exit(1)

    settings = get_settings()
    client = get_qdrant_client(settings)
    assert client is not None, "rag_service.enabled already confirmed Qdrant is configured"
    ensure_collection(client, settings.qdrant_bugs_collection)

    bugs = load_bug_records(path)
    count = rag_service.upsert_bugs(bugs)
    console.print(f"Ingested {count} bug(s) into '{settings.qdrant_bugs_collection}'.")


if __name__ == "__main__":
    app()
