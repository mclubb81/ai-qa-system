def chunk_text(text: str, chunk_size: int = 1000, overlap: int = 100) -> list[str]:
    """A simple sliding-window character chunker. Deliberately minimal --
    no sentence/markdown-aware splitting. Good enough for grounding
    retrieval against short product docs; revisit if real documents turn
    out to need smarter splitting."""
    text = text.strip()
    if not text:
        return []
    if len(text) <= chunk_size:
        return [text]

    step = chunk_size - overlap
    chunks = []
    start = 0
    while start < len(text):
        chunk = text[start : start + chunk_size].strip()
        if chunk:
            chunks.append(chunk)
        start += step
    return chunks
