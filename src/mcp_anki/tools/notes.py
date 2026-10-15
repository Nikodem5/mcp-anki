from typing import Annotated, Any

from mcp.types import ToolAnnotations
from pydantic import BaseModel, Field

from ..anki import anki_request, logged_tool
from ..server import mcp

DEFAULT_NOTE_LIMIT = 50
MAX_BATCH_SIZE = 100


class NoteSpec(BaseModel):
    deck: str = Field(description="Exact deck name. Must already exist; it is not created.")
    fields: dict[str, str] = Field(
        description="Field name -> content. Keys must be real field names of `model` "
        "(see anki_get_model_fields)."
    )
    model: str = Field(default="Basic", description="Exact note type name, e.g. 'Basic' or 'Cloze'.")
    tags: str = Field(default="", description="Space-separated Anki tags. Empty string for none.")


def _model_field_names(model: str) -> list[str]:
    """Field names of `model`, raising a clear ValueError if the model does not exist."""
    models = anki_request("modelNames")
    if model not in models:
        raise ValueError(f"Unknown note type {model!r}. Available: {models}")
    return anki_request("modelFieldNames", modelName=model)


def _check_field_names(model: str, supplied: list[str], valid: list[str]) -> None:
    # AnkiConnect silently drops unknown field names (add, update and canAdd all report
    # success) and matches names case-insensitively. Require exact names so a typo fails loudly.
    unknown = [name for name in supplied if name not in valid]
    if unknown:
        raise ValueError(f"Unknown field(s) {unknown} for note type {model!r}. Valid fields: {valid}")


def _build_fields(front: str | None, back: str | None, fields: dict[str, str] | None) -> dict[str, str]:
    """Merge the front/back shortcuts into the generic fields dict."""
    merged = dict(fields or {})
    for name, value in (("Front", front), ("Back", back)):
        if value is None:
            continue
        if name in merged and merged[name] != value:
            raise ValueError(f"{name} given both as a parameter and in fields with different values")
        merged[name] = value
    return merged


def _note_payload(spec: NoteSpec, field_cache: dict[str, list[str]]) -> dict[str, Any]:
    if spec.model not in field_cache:
        field_cache[spec.model] = _model_field_names(spec.model)
    if not spec.fields:
        raise ValueError("fields must not be empty")
    _check_field_names(spec.model, list(spec.fields), field_cache[spec.model])
    return {
        "deckName": spec.deck,
        "modelName": spec.model,
        "fields": spec.fields,
        "tags": spec.tags.split() if spec.tags else [],
        "options": {"allowDuplicate": False},
    }


def _batch_payloads(notes: list[NoteSpec]) -> list[dict[str, Any]]:
    if not notes:
        raise ValueError("notes must not be empty")
    if len(notes) > MAX_BATCH_SIZE:
        raise ValueError(f"Batch too large: {len(notes)} notes, max {MAX_BATCH_SIZE}")
    cache: dict[str, list[str]] = {}
    payloads = []
    for i, spec in enumerate(notes):
        try:
            payloads.append(_note_payload(spec, cache))
        except ValueError as e:
            raise ValueError(f"notes[{i}]: {e}") from e
    return payloads


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
@logged_tool
def anki_check_exists(
    search_query: Annotated[
        str, Field(description="Anki search syntax, e.g. 'deck:Production front:*hello*'.")
    ],
) -> dict[str, Any]:
    """Search Anki for existing notes matching a query string.

    This is the semantic check: you choose what to search (e.g. the Chinese text in any
    field, across decks). It differs from Anki's own duplicate check, which anki_add_card,
    anki_add_cards and anki_can_add_cards apply mechanically: that one only compares the
    note's FIRST field against other notes of the same note type, so for a Production card
    it compares English prompts and never looks at the Chinese.
    """
    note_ids = anki_request("findNotes", query=search_query)
    return {"exists": len(note_ids) > 0, "count": len(note_ids)}


@mcp.tool()
@logged_tool
def anki_add_card(
    deck: Annotated[
        str,
        Field(description="Exact deck name, as returned by anki_list_decks. The deck must already exist; this will not create one."),
    ],
    front: Annotated[
        str | None,
        Field(description="Shortcut for fields['Front']. Only valid for note types that have a Front field."),
    ] = None,
    back: Annotated[
        str | None,
        Field(description="Shortcut for fields['Back']. Only valid for note types that have a Back field."),
    ] = None,
    fields: Annotated[
        dict[str, str] | None,
        Field(description="Field name -> content, e.g. {'Text': 'The {{c1::cat}} sat.'} for Cloze. Names must match the note type's fields exactly (see anki_get_model_fields)."),
    ] = None,
    model: Annotated[
        str, Field(description="Exact note type name, as returned by anki_list_models.")
    ] = "Basic",
    tags: Annotated[
        str, Field(description="Space-separated Anki tags, e.g. 'chinese hsk4'. Empty string for no tags.")
    ] = "",
) -> dict[str, Any]:
    """Create a single note of any note type in the specified deck.

    Defaults to the Basic note type with front/back. For other types pass `model` and
    `fields`. The model and field names are validated first; unknown ones raise. Anki's
    duplicate check (first field, same note type) rejects the add if it matches.
    """
    spec = NoteSpec(deck=deck, fields=_build_fields(front, back, fields), model=model, tags=tags)
    note_id = anki_request("addNote", note=_note_payload(spec, {}))
    return {"ok": True, "note_id": note_id}


@mcp.tool()
@logged_tool
def anki_add_cards(
    notes: Annotated[
        list[NoteSpec],
        Field(description=f"Notes to create, 1 to {MAX_BATCH_SIZE}. Each has deck, fields, optional model (default Basic) and tags."),
    ],
) -> dict[str, Any]:
    """Create many notes in one call, all-or-nothing.

    Every note is validated first (model, field names, deck, empty first field, Anki's
    first-field duplicate check). If any note fails, AnkiConnect raises and NOTHING is
    added; the error lists the failures. Run anki_can_add_cards first to see per-note
    problems without writing. Avoid repeating a first field within one batch.
    """
    payloads = _batch_payloads(notes)
    note_ids = anki_request("addNotes", notes=payloads)
    return {"ok": True, "added": len(note_ids), "note_ids": note_ids}


@mcp.tool(annotations=ToolAnnotations(readOnlyHint=True))
@logged_tool
def anki_can_add_cards(
    notes: Annotated[
        list[NoteSpec],
        Field(description=f"Notes to check, 1 to {MAX_BATCH_SIZE}, in the same shape as anki_add_cards."),
    ],
) -> dict[str, Any]:
    """Pre-flight a batch without writing anything.

    Reports per note whether Anki would accept it (deck exists, first field not empty, not
    a first-field duplicate of an existing note of the same type). This is Anki's mechanical
    check only; it does not look at the Chinese on a Production card. Use anki_check_exists
    for a semantic search. Does not detect duplicates between notes inside the same batch.
    """
    payloads = _batch_payloads(notes)
    results = anki_request("canAddNotesWithErrorDetail", notes=payloads)
    out = [
        {"index": i, "can_add": r["canAdd"], **({"error": r["error"]} if not r["canAdd"] else {})}
        for i, r in enumerate(results)
    ]
    return {
        "all_ok": all(r["can_add"] for r in out),
        "failed": sum(1 for r in out if not r["can_add"]),
        "results": out,
    }


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
    """Retrieve full note content (all fields, tags, deck, note type) for notes matching a search query."""
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
        str | None, Field(description="Shortcut for fields['Front']. Omit or pass null to leave unchanged.")
    ] = None,
    back: Annotated[
        str | None, Field(description="Shortcut for fields['Back']. Omit or pass null to leave unchanged.")
    ] = None,
    fields: Annotated[
        dict[str, str] | None,
        Field(description="Field name -> new content, for any note type. Only the named fields change. Names must match the note's actual fields exactly (anki_get_notes shows them)."),
    ] = None,
    tags: Annotated[
        str | None,
        Field(description="Space-separated tags to replace the note's entire tag set. Omit or pass null to leave unchanged."),
    ] = None,
) -> dict[str, Any]:
    """Update fields and/or tags of an existing note by ID. Only provided values are changed.

    Field names are validated against the note's real note type; an unknown name raises
    instead of being silently ignored.
    """
    new_fields = _build_fields(front, back, fields)
    if not new_fields and tags is None:
        raise ValueError("Provide at least one of: front, back, fields, tags")
    update_payload: dict[str, Any] = {"id": note_id}
    if new_fields:
        info = anki_request("notesInfo", notes=[note_id])
        if not info or not info[0]:
            raise ValueError(f"Note {note_id} not found")
        _check_field_names(info[0]["modelName"], list(new_fields), list(info[0]["fields"]))
        update_payload["fields"] = new_fields
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
