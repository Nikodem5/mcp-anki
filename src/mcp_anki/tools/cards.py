import html
import re
from datetime import datetime, timezone
from typing import Annotated, Any

from mcp.types import ToolAnnotations
from pydantic import Field

from ..anki import anki_request, logged_tool
from ..server import mcp

DEFAULT_CARD_LIMIT = 25
MAX_CARD_LIMIT = 100
PREVIEW_FIELDS = 3
PREVIEW_CHARS = 60

# Card.type and Card.queue as stored in the collection (Anki's CardType / CardQueue).
CARD_TYPES = {0: "new", 1: "learning", 2: "review", 3: "relearning"}
CARD_QUEUES = {
    -3: "buried (scheduler)",
    -2: "buried (manual)",
    -1: "suspended",
    0: "new",
    1: "learning",
    2: "review",
    3: "day learning",
    4: "preview",
}

_TAG_RE = re.compile(r"<[^>]*>")
_SOUND_RE = re.compile(r"\[sound:[^\]]*\]")


def _preview(fields: dict[str, Any]) -> dict[str, str]:
    """First few non-empty fields, tags and [sound:] markers stripped, truncated."""
    out: dict[str, str] = {}
    for name, value in sorted(fields.items(), key=lambda kv: kv[1].get("order", 0)):
        text = html.unescape(_TAG_RE.sub(" ", _SOUND_RE.sub("", value.get("value", ""))))
        text = " ".join(text.split())
        if not text:
            continue
        out[name] = text if len(text) <= PREVIEW_CHARS else text[: PREVIEW_CHARS - 1] + "…"
        if len(out) == PREVIEW_FIELDS:
            break
    return out


def _due(card: dict[str, Any]) -> dict[str, Any]:
    """Raw `due` plus what it means. Its unit depends on the queue, and the only case that
    could be made a calendar date (review: days since collection creation) needs the
    collection's creation day, which AnkiConnect doesn't expose, so it is left raw."""
    queue, due = card["queue"], card["due"]
    if queue == 0:
        return {"due": due, "due_kind": "new-card position (order in the new queue, not a date)"}
    if queue == 1:
        iso = datetime.fromtimestamp(due, tz=timezone.utc).isoformat()
        return {"due": due, "due_kind": "epoch seconds", "due_at_utc": iso}
    if queue in (2, 3):
        return {"due": due, "due_kind": "day number relative to collection creation (not convertible here)"}
    # Suspended/buried cards keep their pre-suspend due value; its unit follows card.type.
    kind = {0: "new-card position", 1: "epoch seconds", 2: "day number", 3: "day number"}.get(card["type"], "unknown")
    return {"due": due, "due_kind": f"{kind} (card is {CARD_QUEUES.get(queue, queue)}; unit follows type)"}


def _project(card: dict[str, Any]) -> dict[str, Any]:
    factor = card["factor"]
    return {
        "card_id": card["cardId"],
        "note_id": card["note"],
        "deck": card.get("deckName"),
        "model": card.get("modelName"),
        "type": CARD_TYPES.get(card["type"], card["type"]),
        "queue": CARD_QUEUES.get(card["queue"], card["queue"]),
        "interval_days": card["interval"],  # AnkiConnect passes raw ivl; negative would mean seconds
        "ease_percent": factor // 10 if factor else None,  # factor is permille; 0 until first review
        "reps": card["reps"],
        "lapses": card["lapses"],
        "flag": card.get("flags", 0) & 7,
        **_due(card),
        "fields_preview": _preview(card.get("fields", {})),
    }


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
@logged_tool
def anki_get_cards(
    search_query: Annotated[
        str, Field(description="Anki search syntax, e.g. 'deck:Production prop:lapses>3' or 'is:suspended'.")
    ],
    limit: Annotated[
        int | None,
        Field(
            description=f"Maximum number of cards to return (1-{MAX_CARD_LIMIT}, default {DEFAULT_CARD_LIMIT}). Omit or pass null for the default.",
            ge=1,
            le=MAX_CARD_LIMIT,
        ),
    ] = None,
) -> dict[str, Any]:
    """Retrieve card-level scheduling state for cards matching a search query.

    Everything else here is note-level; this exposes what only a card has: interval, ease,
    reps, lapses, due, type and queue. Use it to find leeches or struggling cards, or to see
    what a suspended or new card looks like.

    Each card has: card_id, note_id (usable with anki_get_notes / anki_update_card), deck,
    model, type (new/learning/review/relearning), queue (also reports suspended and buried),
    interval_days, ease_percent (null until first review), reps, lapses, flag (0 = none),
    due + due_kind, and fields_preview (first few non-empty fields, truncated, no HTML).
    Rendered question/answer HTML is deliberately not returned.

    `due` is raw and its unit depends on the card: due_kind says which. For new cards it is a
    queue position; for learning cards due_at_utc is given; for review cards it is a day
    number relative to the collection's creation date, which cannot be turned into a date
    through AnkiConnect. To find cards due by a date, put that in the query (is:due,
    prop:due<=7) rather than reading `due`.

    Results are capped at `limit`; `matched` is the total the query found. Only the returned
    slice is fetched in detail.
    """
    limit = DEFAULT_CARD_LIMIT if limit is None else limit
    card_ids = anki_request("findCards", query=search_query)
    matched = len(card_ids)
    card_ids = card_ids[:limit]
    if not card_ids:
        return {"matched": matched, "returned": 0, "cards": []}
    infos = anki_request("cardsInfo", cards=card_ids)
    # cardsInfo returns {} for an id that vanished between the two calls.
    cards = [_project(c) for c in infos if c]
    return {"matched": matched, "returned": len(cards), "cards": cards}
