import json
from pathlib import Path

from qa_agent.rag.chunking import chunk_text

DOC_EXTENSIONS = {".md", ".txt"}


def load_doc_chunks(path: Path, chunk_size: int = 1000, overlap: int = 100) -> list[tuple[str, str]]:
    """Glob .md/.txt files under `path` (or just `path` if it's a file),
    chunk each file's text. Returns (chunk_text, source_label) pairs."""
    if path.is_file():
        files = [path]
    else:
        files = sorted(p for p in path.rglob("*") if p.suffix.lower() in DOC_EXTENSIONS)

    chunks: list[tuple[str, str]] = []
    for file in files:
        text = file.read_text()
        for chunk in chunk_text(text, chunk_size=chunk_size, overlap=overlap):
            chunks.append((chunk, str(file)))
    return chunks


def load_bug_records(path: Path) -> list[dict]:
    """Parse a JSON file containing a list of
    {"id"?: str, "title": str, "description": str, "severity"?: str}."""
    records = json.loads(path.read_text())
    if not isinstance(records, list):
        raise ValueError(f"{path} must contain a JSON list of bug records.")
    return records
