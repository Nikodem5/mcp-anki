from typing import Annotated, Any

from mcp.types import ToolAnnotations
from pydantic import Field

from ..anki import anki_request, logged_tool
from ..server import mcp

DEFAULT_NOTE_LIMIT = 50


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
@logged_tool
def anki_check_exists(
    search_query: Annotated[
        str, Field(description="Anki search syntax, e.g. 'deck:Production front:*hello*'.")
    ],
) -> dict[str, Any]:
    """Search Anki for existing notes matching a query string."""
    note_ids = anki_request("findNotes", query=search_query)
    return {"exists": len(note_ids) > 0, "count": len(note_ids)}


@mcp.tool()
@logged_tool
def anki_add_card(
    deck: Annotated[
        str,
        Field(description="Exact deck name, as returned by anki_list_decks. The deck must already exist; this will not create one."),
    ],
    front: Annotated[str, Field(description="Content for the note's Front field.")],
    back: Annotated[str, Field(description="Content for the note's Back field.")],
    tags: Annotated[
        str, Field(description="Space-separated Anki tags, e.g. 'chinese hsk4'. Empty string for no tags.")
    ] = "",
) -> dict[str, Any]:
    """Create a single Anki card in the specified deck. Only the Basic note type is supported."""
    note = {
        "deckName": deck,
        "modelName": "Basic",
        "fields": {"Front": front, "Back": back},
        "tags": tags.split() if tags else [],
        "options": {"allowDuplicate": False},
    }
    note_id = anki_request("addNote", note=note)
    return {"ok": True, "note_id": note_id}


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
@logged_tool
def anki_get_notes(
    search_query: Annotated[
        str, Field(description="Anki search syntax, e.g. 'deck:Production tag:leech'.")
    ],
    limit: Annotated[
        int, Field(description="Maximum number of notes to return.", gt=0)
    ] = DEFAULT_NOTE_LIMIT,
) -> dict[str, Any]:
    """Retrieve full note content (front, back, tags, deck) for notes matching a search query."""
    note_ids = anki_request("findNotes", query=search_query)
    matched = len(note_ids)
    note_ids = note_ids[:limit]
    if not note_ids:
        return {"matched": matched, "returned": 0, "notes": []}

    notes_info = anki_request("notesInfo", notes=note_ids)

    # getDecks maps deck name -> card IDs directly from the collection, unlike cardsInfo,
    # which renders every card's question/answer HTML just to report its deck.
    all_card_ids = [cid for note in notes_info for cid in note.get("cards", [])]
    card_to_deck: dict[int, str] = {}
    if all_card_ids:
        decks = anki_request("getDecks", cards=all_card_ids)
        for deck_name, card_ids in decks.items():
            for cid in card_ids:
                card_to_deck[cid] = deck_name

    results = []
    for note in notes_info:
        card_ids = note.get("cards", [])
        results.append({
            "note_id": note["noteId"],
            "deck": card_to_deck.get(card_ids[0]) if card_ids else None,
            "fields": {k: v["value"] for k, v in note["fields"].items()},
            "tags": note["tags"],
            "model": note["modelName"],
        })
    return {"matched": matched, "returned": len(results), "notes": results}


@mcp.tool()
@logged_tool
def anki_update_card(
    note_id: Annotated[
        int, Field(description="The Anki note ID to update, as returned by anki_add_card or anki_get_notes.")
    ],
    front: Annotated[
        str | None, Field(description="New content for the Front field. Omit or pass null to leave unchanged.")
    ] = None,
    back: Annotated[
        str | None, Field(description="New content for the Back field. Omit or pass null to leave unchanged.")
    ] = None,
    tags: Annotated[
        str | None,
        Field(description="Space-separated tags to replace the note's entire tag set. Omit or pass null to leave unchanged."),
    ] = None,
) -> dict[str, Any]:
    """Update the front, back, and/or tags of an existing note by ID. Only provided fields are changed."""
    if front is None and back is None and tags is None:
        raise ValueError("Provide at least one of: front, back, tags")
    update_payload: dict[str, Any] = {"id": note_id}
    # updateNoteFields only assigns field names it's given and leaves the rest untouched, so
    # sending just {"Front": ...} already updates only Front — no need to read the note back
    # first to fill in the field that wasn't provided.
    fields = {}
    if front is not None:
        fields["Front"] = front
    if back is not None:
        fields["Back"] = back
    if fields:
        update_payload["fields"] = fields
    if tags is not None:
        update_payload["tags"] = tags.split()
    anki_request("updateNote", note=update_payload)
    return {"ok": True, "note_id": note_id}


@mcp.tool(annotations=ToolAnnotations(destructiveHint=True))
@logged_tool
def anki_delete_note(
    note_id: Annotated[
        int, Field(description="The Anki note ID to delete, as returned by anki_add_card or anki_get_notes.")
    ],
) -> dict[str, Any]:
    """Hard-delete a note and all its cards from Anki. Not undoable through this API."""
    anki_request("deleteNotes", notes=[note_id])
    return {"ok": True}
