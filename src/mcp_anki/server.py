from mcp.server.fastmcp import FastMCP

mcp = FastMCP("mcp-anki")

# Side-effecting imports: each module registers its tools on `mcp` via @mcp.tool().
from .tools import decks, health, notes, scheduling  # noqa: E402,F401
