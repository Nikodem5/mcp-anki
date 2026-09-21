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
