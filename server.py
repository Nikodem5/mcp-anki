import json
import logging
import urllib.request
from functools import wraps

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("chunk-factory")

_logger = logging.getLogger("mcp_tools")
_logger.setLevel(logging.DEBUG)
_handler = logging.FileHandler("mcp_tools.log", encoding="utf-8")
_handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
_logger.addHandler(_handler)


def logged_tool(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        _logger.info(f"CALL {fn.__name__} | args={kwargs}")
        try:
            result = fn(*args, **kwargs)
            _logger.info(f"  OK {fn.__name__} | result={str(result)[:200]}")
            return result
        except Exception as e:
            _logger.error(f" ERR {fn.__name__} | {e}")
            raise
    return wrapper


def anki_request(action: str, **params):
    payload = {"action": action, "version": 6}
    if params:
        payload["params"] = params
    req = urllib.request.Request(
        "http://localhost:8765",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        result = json.loads(resp.read())
    if result.get("error"):
        raise Exception(f"AnkiConnect: {result['error']}")
    return result.get("result")


@mcp.tool()
@logged_tool
def hello() -> str:
    """Ping to verify the MCP server is running."""
    return "Chunk Factory MCP server is running."


@mcp.tool()
@logged_tool
def test_anki_connection() -> str:
    """Check whether AnkiConnect is reachable."""
    try:
        version = anki_request("version")
        return json.dumps({"connected": True, "version": version})
    except Exception as e:
        return json.dumps({"connected": False, "error": str(e)})


@mcp.tool()
@logged_tool
def anki_check_exists(search_query: str) -> str:
    """Search Anki for existing notes matching a query string."""
    try:
        note_ids = anki_request("findNotes", query=search_query)
        return json.dumps({"exists": len(note_ids) > 0, "count": len(note_ids)})
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
@logged_tool
def anki_add_card(deck: str, front: str, back: str, tags: str = "") -> str:
    """Create a single Anki card in the specified deck."""
    try:
        note = {
            "deckName": deck,
            "modelName": "Basic",
            "fields": {"Front": front, "Back": back},
            "tags": tags.split() if tags else [],
            "options": {"allowDuplicate": False},
        }
        note_id = anki_request("addNote", note=note)
        return json.dumps({"ok": True, "note_id": note_id})
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
@logged_tool
def anki_get_notes(search_query: str) -> str:
    """Retrieve full note content (front, back, tags, deck) for all notes matching a search query."""
    try:
        note_ids = anki_request("findNotes", query=search_query)
        if not note_ids:
            return json.dumps({"notes": []})
        notes_info = anki_request("notesInfo", notes=note_ids)
        results = []
        for note in notes_info:
            results.append({
                "note_id": note["noteId"],
                "deck": note.get("cards", [None])[0],  # card ID placeholder; deck resolved below
                "fields": {k: v["value"] for k, v in note["fields"].items()},
                "tags": note["tags"],
                "model": note["modelName"],
            })
        # Resolve deck names via cardsInfo
        all_card_ids = [cid for note in notes_info for cid in note.get("cards", [])]
        if all_card_ids:
            cards_info = anki_request("cardsInfo", cards=all_card_ids)
            card_to_deck = {c["cardId"]: c["deckName"] for c in cards_info}
            for i, note in enumerate(notes_info):
                card_ids = note.get("cards", [])
                results[i]["deck"] = card_to_deck.get(card_ids[0]) if card_ids else None
        return json.dumps({"notes": results})
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
@logged_tool
def anki_update_card(note_id: int, front: str = None, back: str = None, tags: str = None) -> str:
    """Update the front, back, and/or tags of an existing note by ID. Only provided fields are changed."""
    try:
        if front is None and back is None and tags is None:
            return json.dumps({"error": "Provide at least one of: front, back, tags"})
        update_payload = {"id": note_id}
        if front is not None or back is not None:
            # Fetch current fields to fill in whichever wasn't provided
            notes_info = anki_request("notesInfo", notes=[note_id])
            if not notes_info:
                return json.dumps({"error": "Note not found"})
            current_fields = {k: v["value"] for k, v in notes_info[0]["fields"].items()}
            update_payload["fields"] = {
                "Front": front if front is not None else current_fields.get("Front", ""),
                "Back": back if back is not None else current_fields.get("Back", ""),
            }
        if tags is not None:
            update_payload["tags"] = tags.split()
        anki_request("updateNote", note=update_payload)
        return json.dumps({"ok": True, "note_id": note_id})
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
@logged_tool
def anki_delete_note(note_id: int) -> str:
    """Hard-delete a note and all its cards from Anki."""
    try:
        anki_request("deleteNotes", notes=[note_id])
        return json.dumps({"ok": True})
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
@logged_tool
def anki_get_deck_preset_limits(deck: str) -> str:
    """Get a deck's new-cards/day and reviews/day limits from its Preset config, and whether that Preset is shared with other decks.

    IMPORTANT: this reads only the Preset tier. Anki has three limit tiers (Today only > This deck > Preset,
    highest precedence first); a per-deck "This deck" or "Today only" override in Anki's Deck Options can exist
    on top of this and is invisible here — AnkiConnect has no action to read it. If the numbers shown in the
    Anki app don't match what this returns, check the "This deck"/"Today only" tabs in Deck Options manually,
    and use anki_get_deck_stats to see the real effective counts Anki's scheduler is using today.
    """
    try:
        config = anki_request("getDeckConfig", deck=deck)
        if not config:
            return json.dumps({"error": f"Deck not found: {deck}"})
        all_decks = anki_request("deckNames")
        shared_with = []
        for d in all_decks:
            if d == deck:
                continue
            other = anki_request("getDeckConfig", deck=d)
            if other and other.get("id") == config.get("id"):
                shared_with.append(d)
        return json.dumps({
            "deck": deck,
            "config_name": config.get("name"),
            "config_id": config.get("id"),
            "new_per_day": config.get("new", {}).get("perDay"),
            "review_per_day": config.get("rev", {}).get("perDay"),
            "shared_with": shared_with,
        })
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
@logged_tool
def anki_set_deck_preset_limits(deck: str, new_per_day: int = None, review_per_day: int = None) -> str:
    """Set a deck's new-cards/day and/or reviews/day limit on its Preset config; auto-clones a shared Preset to a deck-only one first so other decks aren't affected.

    IMPORTANT: this writes only the Preset tier. Anki has three limit tiers (Today only > This deck > Preset,
    highest precedence first); if the deck has a "This deck" or "Today only" override set in Anki's Deck Options,
    this call will report success and change the Preset, but the override will keep taking precedence and the
    app will keep showing the old numbers — AnkiConnect has no action to read or write that override tier, so it
    must be cleared manually in the Anki app. ALWAYS call anki_get_deck_stats after this to verify the change
    actually took effect in the real scheduler counts, not just in the config.
    """
    try:
        if new_per_day is None and review_per_day is None:
            return json.dumps({"error": "Provide at least one of: new_per_day, review_per_day"})
        config = anki_request("getDeckConfig", deck=deck)
        if not config:
            return json.dumps({"error": f"Deck not found: {deck}"})

        all_decks = anki_request("deckNames")
        shared_with = [
            d for d in all_decks
            if d != deck and (anki_request("getDeckConfig", deck=d) or {}).get("id") == config.get("id")
        ]

        cloned = False
        if shared_with:
            new_config_id = anki_request(
                "cloneDeckConfigId", name=f"{deck} (dedicated)", cloneFrom=str(config["id"])
            )
            anki_request("setDeckConfigId", decks=[deck], configId=new_config_id)
            config = anki_request("getDeckConfig", deck=deck)
            cloned = True

        if new_per_day is not None:
            config.setdefault("new", {})["perDay"] = new_per_day
        if review_per_day is not None:
            config.setdefault("rev", {})["perDay"] = review_per_day

        anki_request("saveDeckConfig", config=config)
        return json.dumps({
            "ok": True,
            "deck": deck,
            "new_per_day": config.get("new", {}).get("perDay"),
            "review_per_day": config.get("rev", {}).get("perDay"),
            "cloned_dedicated_config": cloned,
            "was_shared_with": shared_with,
        })
    except Exception as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
@logged_tool
def anki_get_deck_stats(deck: str) -> str:
    """Get the actual today's new/learn/review counts Anki's scheduler computes for a deck — the real numbers behind what the app UI shows, unlike deck config which is just the configured limit."""
    try:
        stats = anki_request("getDeckStats", decks=[deck])
        if not stats:
            return json.dumps({"error": f"No stats returned for deck: {deck}"})
        for entry in stats.values():
            if entry.get("name") == deck:
                return json.dumps(entry)
        return json.dumps(stats)
    except Exception as e:
        return json.dumps({"error": str(e)})


if __name__ == "__main__":
    mcp.run()
