"""Manual diagnostic: launch Playwright MCP, list tools, run a tiny smoke test.

Usage: python scripts/check_mcp.py
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from qa_agent.mcp.playwright_client import PlaywrightMCPSession


async def main() -> None:
    async with PlaywrightMCPSession(headless=True) as session:
        print("Discovered tools:")
        for tool in session.tools:
            print(f"  - {tool.name}: {tool.description[:80]}")

        by_name = {t.name: t for t in session.tools}
        navigate = by_name.get("browser_navigate")
        snapshot = by_name.get("browser_snapshot")
        screenshot = by_name.get("browser_take_screenshot")

        if navigate:
            print("\n--- browser_navigate(https://example.com) ---")
            result = await navigate.ainvoke({"url": "https://example.com"})
            print(type(result), repr(result)[:500])

        if snapshot:
            print("\n--- browser_snapshot() ---")
            result = await snapshot.ainvoke({})
            print(type(result), repr(result)[:800])

        if screenshot:
            print("\n--- browser_take_screenshot() ---")
            result = await screenshot.ainvoke({})
            print("type:", type(result))
            if isinstance(result, tuple):
                for i, part in enumerate(result):
                    print(f"  part[{i}] type={type(part)}")
                    if isinstance(part, list):
                        for j, item in enumerate(part):
                            print(f"    item[{j}] = {repr(item)[:300]}")
                    else:
                        print("   ", repr(part)[:300])
            else:
                print(repr(result)[:800])


if __name__ == "__main__":
    asyncio.run(main())
