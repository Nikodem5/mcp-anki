from typing import Any

from mcp.types import ToolAnnotations

from ..anki import anki_request, logged_tool, logger
from ..server import mcp


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
@logged_tool
def test_anki_connection() -> dict[str, Any]:
    """Check whether AnkiConnect is reachable."""
    # Shaped as {"connected": False, ...} rather than raising, so the caller doesn't have to
    # distinguish an MCP-level error from "Anki isn't running" — but that means logged_tool's
    # own except branch never sees this, so the failure is logged here explicitly instead.
    try:
        version = anki_request("version")
        return {"connected": True, "version": version}
    except Exception as e:
        logger.error(f" ERR test_anki_connection | {e}")
        return {"connected": False, "error": str(e)}


@mcp.tool()
@logged_tool
def anki_sync() -> dict[str, Any]:
    """Sync the local collection with AnkiWeb, so cards added or edited here reach the user's other devices. Safe to call after a batch of writes."""
    # AnkiConnect returns null on success; report the call itself instead.
    anki_request("sync")
    return {"synced": True}
