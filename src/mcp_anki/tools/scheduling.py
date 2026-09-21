from typing import Annotated, Any

from mcp.types import ToolAnnotations
from pydantic import Field

from ..anki import anki_request, logged_tool
from ..server import mcp


@mcp.tool(annotations=ToolAnnotations(destructiveHint=True))
@logged_tool
def anki_reschedule_cards(
    search_query: Annotated[
        str, Field(description="Anki search syntax selecting the cards to reschedule, e.g. 'deck:HSK4 is:due'.")
    ],
    days: Annotated[
        str,
        Field(description="Anki setDueDate syntax: '0' due today, '1!' due tomorrow and reset interval to 1 day, '3-7' a random day in that range."),
    ],
    dry_run: Annotated[
        bool,
        Field(description="Preview only when true (default). Set to false only after showing the user the query and count and getting their confirmation."),
    ] = True,
) -> dict[str, Any]:
    """Preview, or apply, a change to when every card matching an Anki search query is next due.

    This moves the cards, not the deck's limits — which is why it still works when a deck's
    daily limit can't be lowered. Typical use is spreading a backlog of due cards back out
    over the following days.

    `days` uses Anki's setDueDate syntax:
      "0"    due today
      "1!"   due tomorrow, AND reset the card's interval to 1 day
      "3-7"  a random day from 3 to 7 days out — a range is what spreads a pile out

    DESTRUCTIVE, AND NOT UNDOABLE THROUGH THIS API. It overwrites the due date of every
    matched card, turns new cards into review cards, and with a "!" suffix discards the
    interval the card had learned. The only undo is Ctrl+Z inside the Anki app, immediately,
    before anything else changes the collection. Previous due dates cannot be recovered
    afterwards.

    dry_run is True by default and writes nothing: it runs the search only and reports how
    many cards WOULD be rescheduled. Always call it that way first, show the user the query
    and the count, and call again with dry_run=False only after they confirm that exact
    query. Do not pass dry_run=False on your own initiative.

    The query is re-run when applying, so a time-sensitive query such as "is:due" can match a
    different set of cards than the preview reported if reviews happened in between.
    """
    card_ids = anki_request("findCards", query=search_query)
    if dry_run:
        return {
            "dry_run": True,
            "query": search_query,
            "days": days,
            "would_reschedule": len(card_ids),
            "note": "Nothing was changed. Call again with dry_run=false to apply.",
        }
    if not card_ids:
        return {"ok": True, "query": search_query, "rescheduled": 0}
    anki_request("setDueDate", cards=card_ids, days=days)
    return {
        "ok": True,
        "query": search_query,
        "days": days,
        "rescheduled": len(card_ids),
    }
