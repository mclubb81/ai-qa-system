import base64
from pathlib import Path

from langchain_core.messages import AIMessage, ToolMessage

from qa_agent.agents.executor import extract_screenshots, extract_tool_calls

_TINY_PNG_B64 = base64.b64encode(b"not-a-real-png-but-fine-for-a-test").decode()


def _fake_transcript() -> list:
    return [
        AIMessage(
            content="",
            tool_calls=[{"name": "browser_navigate", "args": {"url": "https://example.com"}, "id": "call_1"}],
        ),
        ToolMessage(
            content=[{"type": "text", "text": "Navigated"}],
            tool_call_id="call_1",
        ),
        AIMessage(
            content="",
            tool_calls=[{"name": "browser_take_screenshot", "args": {}, "id": "call_2"}],
        ),
        ToolMessage(
            content=[
                {"type": "text", "text": "Screenshot taken"},
                {"type": "image", "base64": _TINY_PNG_B64, "mime_type": "image/png"},
            ],
            tool_call_id="call_2",
        ),
    ]


def test_extract_tool_calls_pairs_calls_with_results():
    transcript = extract_tool_calls(_fake_transcript())
    assert transcript == [
        {"tool_name": "browser_navigate", "args": {"url": "https://example.com"}, "result": "Navigated"},
        {"tool_name": "browser_take_screenshot", "args": {}, "result": "Screenshot taken [image attached]"},
    ]


def test_extract_screenshots_decodes_and_saves_images(tmp_path: Path):
    screenshot_dir = tmp_path / "screenshots"
    refs = extract_screenshots(_fake_transcript(), screenshot_dir, prefix="TC-01")

    assert refs == ["screenshots/TC-01-1.png"]
    saved = screenshot_dir / "TC-01-1.png"
    assert saved.exists()
    assert saved.read_bytes() == base64.b64decode(_TINY_PNG_B64)


def test_extract_screenshots_returns_empty_list_when_no_images():
    refs = extract_screenshots(
        [ToolMessage(content=[{"type": "text", "text": "no image here"}], tool_call_id="x")],
        Path("/tmp/unused-screenshot-dir-for-test"),
        prefix="TC-01",
    )
    assert refs == []
