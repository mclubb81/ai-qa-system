from contextlib import AsyncExitStack

from langchain_core.tools import BaseTool
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.tools import load_mcp_tools

_SERVER_NAME = "playwright"


class PlaywrightMCPSession:
    """Owns the lifecycle of a single @playwright/mcp subprocess + browser.

    Use as an async context manager, exactly once per CLI run:

        async with PlaywrightMCPSession(headless=True) as session:
            tools = session.tools
            ...

    IMPORTANT: langchain-mcp-adapters' `MultiServerMCPClient.get_tools()`
    opens a brand-new session (and therefore a brand-new stdio subprocess +
    browser, for this stdio-based server) for *every individual tool call*
    unless a session is held open explicitly. That would reset the browser
    between every click/navigate, breaking state across a test case's
    steps. To keep one browser alive for the whole run, we open
    `client.session(...)` once via an AsyncExitStack and bind `.tools` to
    that single persistent session via `load_mcp_tools(session)`.

    Closing the session tears down the stdio transport, which terminates
    the npx/@playwright/mcp child process and the browser it owns.
    """

    def __init__(self, headless: bool = True) -> None:
        self._headless = headless
        self._client: MultiServerMCPClient | None = None
        self._exit_stack: AsyncExitStack | None = None
        self.tools: list[BaseTool] = []

    async def __aenter__(self) -> "PlaywrightMCPSession":
        args = ["-y", "@playwright/mcp@latest"]
        if self._headless:
            args.append("--headless")

        self._client = MultiServerMCPClient(
            {
                _SERVER_NAME: {
                    "command": "npx",
                    "args": args,
                    "transport": "stdio",
                }
            }
        )
        self._exit_stack = AsyncExitStack()
        session = await self._exit_stack.enter_async_context(
            self._client.session(_SERVER_NAME)
        )
        self.tools = await load_mcp_tools(session)
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self._exit_stack is not None:
            await self._exit_stack.aclose()
