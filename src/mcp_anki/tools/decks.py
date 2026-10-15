from typing import Annotated, Any

from mcp.types import ToolAnnotations
from pydantic import Field

from ..anki import anki_request, logged_tool
from ..server import mcp

DECK_FIELD = Field(description="Exact deck name, as returned by anki_list_decks.")


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
@logged_tool
def anki_list_decks() -> dict[str, Any]:
    """List every deck name in the collection, for getting exact deck names to pass to the other tools."""
    return {"decks": anki_request("deckNames")}


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
@logged_tool
def anki_get_deck_preset_limits(deck: Annotated[str, DECK_FIELD]) -> dict[str, Any]:
    """Get a deck's new-cards/day and reviews/day limits from its Preset config, and whether that Preset is shared with other decks.

    IMPORTANT: this reads only the Preset tier. Anki has three limit tiers (Today only > This deck > Preset,
    highest precedence first); a per-deck "This deck" or "Today only" override in Anki's Deck Options can exist
    on top of this and is invisible here — AnkiConnect has no action to read it. If the numbers shown in the
    Anki app don't match what this returns, check the "This deck"/"Today only" tabs in Deck Options manually,
    and use anki_get_deck_stats to see the real effective counts Anki's scheduler is using today.
    """
    config = anki_request("getDeckConfig", deck=deck)
    if not config:
        return {"error": f"Deck not found: {deck}"}
    all_decks = anki_request("deckNames")
    shared_with = []
    for d in all_decks:
        if d == deck:
            continue
        other = anki_request("getDeckConfig", deck=d)
        if other and other.get("id") == config.get("id"):
            shared_with.append(d)
    return {
        "deck": deck,
        "config_name": config.get("name"),
        "config_id": config.get("id"),
        "new_per_day": config.get("new", {}).get("perDay"),
        "review_per_day": config.get("rev", {}).get("perDay"),
        "shared_with": shared_with,
    }


@mcp.tool()
@logged_tool
def anki_set_deck_preset_limits(
    deck: Annotated[str, DECK_FIELD],
    new_per_day: Annotated[
        int | None, Field(description="New cards/day limit to set on the deck's Preset. Omit or pass null to leave unchanged.")
    ] = None,
    review_per_day: Annotated[
        int | None, Field(description="Reviews/day limit to set on the deck's Preset. Omit or pass null to leave unchanged.")
    ] = None,
) -> dict[str, Any]:
    """Set a deck's new-cards/day and/or reviews/day limit on its Preset config; auto-clones a shared Preset to a deck-only one first so other decks aren't affected.

    IMPORTANT: this writes only the Preset tier. Anki has three limit tiers (Today only > This deck > Preset,
    highest precedence first); if the deck has a "This deck" or "Today only" override set in Anki's Deck Options,
    this call will report success and change the Preset, but the override will keep taking precedence and the
    app will keep showing the old numbers — AnkiConnect has no action to read or write that override tier, so it
    must be cleared manually in the Anki app. ALWAYS call anki_get_deck_stats after this to verify the change
    actually took effect in the real scheduler counts, not just in the config.
    """
    if new_per_day is None and review_per_day is None:
        raise ValueError("Provide at least one of: new_per_day, review_per_day")
    config = anki_request("getDeckConfig", deck=deck)
    if not config:
        return {"error": f"Deck not found: {deck}"}

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
    return {
        "ok": True,
        "deck": deck,
        "new_per_day": config.get("new", {}).get("perDay"),
        "review_per_day": config.get("rev", {}).get("perDay"),
        "cloned_dedicated_config": cloned,
        "was_shared_with": shared_with,
    }


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
@logged_tool
def anki_get_deck_stats(deck: Annotated[str, DECK_FIELD]) -> dict[str, Any]:
    """Get the actual today's new/learn/review counts Anki's scheduler computes for a deck — the real numbers behind what the app UI shows, unlike deck config which is just the configured limit. Read-only; pass the deck's full path, as returned by anki_list_decks."""
    # Not just validation: AnkiConnect's getDeckStats CREATES a deck when handed a name that
    # doesn't exist, so an unchecked typo would silently add an empty deck to the collection.
    if deck not in anki_request("deckNames"):
        return {"error": f"Deck not found: {deck}"}
    stats = anki_request("getDeckStats", decks=[deck])
    if not stats:
        return {
            "error": f"Deck exists but AnkiConnect returned no stats for it "
                     f"(usually means the deck holds no cards): {deck}"
        }
    # AnkiConnect reports `name` as the deck's basename ("e. HSK4"), not the full path
    # ("Mandarin: Vocabulary::e. HSK4") the caller passes in — its README sample shows
    # the full path, but live Anki does not. Match either, and fall back to the single
    # entry, since one requested deck can only produce one result.
    basename = deck.split("::")[-1]
    entry = None
    if len(stats) == 1:
        entry = next(iter(stats.values()))
    else:
        for candidate in stats.values():
            if candidate.get("name") in (deck, basename):
                entry = candidate
                break
    if entry is None:
        return stats
    # `name` alone is ambiguous once it's a basename, so echo back what was asked for.
    return {"deck": deck, **entry}


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
@logged_tool
def anki_list_decks_with_ids(
    limit: Annotated[int, Field(description="Maximum number of decks to return.", ge=1, le=1000)] = 200,
) -> dict[str, Any]:
    """List decks as {name, id} pairs. Same names as anki_list_decks, plus the numeric deck id. Read-only."""
    mapping = anki_request("deckNamesAndIds")
    decks = [{"name": name, "id": deck_id} for name, deck_id in mapping.items()]
    return {"total": len(decks), "decks": decks[:limit], "truncated": len(decks) > limit}


@mcp.tool(annotations=ToolAnnotations(idempotentHint=True))
@logged_tool
def anki_create_deck(
    deck: Annotated[str, Field(description="Full deck name to create; use '::' for nesting, e.g. 'Mandarin::Production'.")],
) -> dict[str, Any]:
    """Create a deck if it does not exist. Safe to call for an existing deck: nothing is changed and `created` is false.

    anki_add_card does not auto-create decks, so use this first when a target deck is missing.
    """
    if not deck.strip():
        raise ValueError("deck must not be empty")
    existed = deck in anki_request("deckNames")
    deck_id = anki_request("createDeck", deck=deck)
    return {"ok": True, "deck": deck, "id": deck_id, "created": not existed}


def _deck_query(deck: str) -> str:
    escaped = deck.replace("\\", "\\\\").replace('"', '\\"').replace("*", r"\*").replace("_", r"\_")
    return f'deck:"{escaped}"'


@mcp.tool(annotations=ToolAnnotations(destructiveHint=False, idempotentHint=True))
@logged_tool
def anki_move_cards(
    deck: Annotated[str, Field(description="Exact name of the existing destination deck.")],
    card_ids: Annotated[list[int] | None, Field(description="Card ids to move. Provide this or query, not both.")] = None,
    query: Annotated[str | None, Field(description="Anki search query selecting the cards to move. Provide this or card_ids.")] = None,
    limit: Annotated[int, Field(description="Safety cap: refuse (move nothing) if more cards than this match.", ge=1, le=10000)] = 500,
) -> dict[str, Any]:
    """Move existing cards to another existing deck.

    Not gated by dry_run because it is reversible: the result lists `moved_from` (source deck ->
    count), so cards can be moved back. The count is resolved before writing and the call refuses
    if it exceeds `limit`. The destination must already exist (AnkiConnect's changeDeck would
    silently create it; use anki_create_deck first). Scheduling data is preserved.
    """
    if (card_ids is None) == (query is None):
        raise ValueError("Provide exactly one of: card_ids, query")
    if deck not in anki_request("deckNames"):
        return {"error": f"Deck not found: {deck}"}
    ids = card_ids if card_ids is not None else anki_request("findCards", query=query)
    if not ids:
        return {"ok": True, "deck": deck, "moved": 0}
    if len(ids) > limit:
        return {"error": f"{len(ids)} cards match, above limit={limit}; nothing moved. Narrow the selection or raise limit."}
    sources = anki_request("getDecks", cards=ids)
    moved_from = {name: len(cids) for name, cids in sources.items()}
    anki_request("changeDeck", cards=ids, deck=deck)
    return {"ok": True, "deck": deck, "moved": len(ids), "moved_from": moved_from}


@mcp.tool(annotations=ToolAnnotations(destructiveHint=True))
@logged_tool
def anki_delete_deck(
    deck: Annotated[str, DECK_FIELD],
    dry_run: Annotated[bool, Field(description="If true (default), only report what would be deleted. Do not pass false unless the user explicitly asked for the deletion.")] = True,
) -> dict[str, Any]:
    """Delete a deck, ALL its subdecks, and ALL cards in them. DESTRUCTIVE; cannot be undone through this API.

    Defaults to dry_run=True, which returns the subdecks and card count that would be removed
    without writing. Do NOT pass dry_run=False unprompted: show the user the preview and
    get explicit confirmation first. AnkiConnect only supports deleting a deck together with
    its cards (cardsToo is mandatory), so to keep the cards, move them first with anki_move_cards.
    The built-in 'Default' deck is refused. Nonexistent decks are refused.
    """
    all_decks = anki_request("deckNames")
    if deck not in all_decks:
        return {"error": f"Deck not found: {deck}"}
    if deck == "Default":
        return {"error": "Refusing to delete the built-in 'Default' deck."}
    affected = [d for d in all_decks if d == deck or d.startswith(deck + "::")]
    card_count = len(anki_request("findCards", query=_deck_query(deck)))
    preview = {"deck": deck, "decks_affected": affected, "cards_affected": card_count}
    if dry_run:
        return {"dry_run": True, **preview}
    anki_request("deleteDecks", decks=[deck], cardsToo=True)
    return {"dry_run": False, "ok": True, **preview}
