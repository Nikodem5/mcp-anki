"""Input validation: bad input becomes an error payload and nothing is written."""
import asyncio

import pytest
from mcp.server.fastmcp.exceptions import ToolError

from conftest import mcp
from mcp_anki.tools.notes import NoteSpec


def _nothing_written(anki):
    assert not [a for a in anki.actions() if a in ("addNote", "addNotes", "updateNote", "updateNoteFields")]


def test_add_card_unknown_model(anki, tool):
    r = tool("anki_add_card")("Default", fields={"Front": "a"}, model="Nope")
    assert "Unknown note type" in r["error"]
    _nothing_written(anki)


def test_add_card_unknown_field(anki, tool):
    r = tool("anki_add_card")("Default", fields={"Frnt": "a"})
    assert "Unknown field" in r["error"]
    _nothing_written(anki)


def test_add_card_field_names_are_case_sensitive(anki, tool):
    assert "error" in tool("anki_add_card")("Default", fields={"front": "a"})
    _nothing_written(anki)


def test_add_card_ok(anki, tool):
    r = tool("anki_add_card")("Default", front="hi", back="yo", tags="a b")
    assert r["ok"]
    assert anki.of("addNote")[0]["note"]["tags"] == ["a", "b"]
    assert anki.notes[r["note_id"]]["fields"] == {"Front": "hi", "Back": "yo"}


def test_add_card_front_conflicts_with_fields(anki, tool):
    r = tool("anki_add_card")("Default", front="a", fields={"Front": "b"})
    assert "different values" in r["error"]
    _nothing_written(anki)


def test_add_card_front_equal_to_fields_is_fine(anki, tool):
    assert tool("anki_add_card")("Default", front="a", fields={"Front": "a"})["ok"]


def test_add_card_front_on_cloze_rejected(anki, tool):
    r = tool("anki_add_card")("Default", front="a", model="Cloze")
    assert "Unknown field" in r["error"]
    _nothing_written(anki)


def test_add_card_missing_deck_not_created(anki, tool):
    r = tool("anki_add_card")("NoDeck", front="a")
    assert "error" in r and "NoDeck" not in anki.decks


def test_add_card_empty_fields(anki, tool):
    assert "error" in tool("anki_add_card")("Default")
    _nothing_written(anki)


def test_add_cards_unknown_model_and_field(anki, tool):
    fn = tool("anki_add_cards")
    r = fn([NoteSpec(deck="Default", fields={"Front": "a"}, model="Nope")])
    assert "notes[0]" in r["error"]
    r = fn([NoteSpec(deck="Default", fields={"Front": "ok"}), NoteSpec(deck="Default", fields={"Bad": "a"})])
    assert "notes[1]" in r["error"]
    _nothing_written(anki)


def test_add_cards_batch_limits(anki, tool):
    fn = tool("anki_add_cards")

    def spec(i):
        return NoteSpec(deck="Default", fields={"Front": str(i)})

    assert "too large" in fn([spec(i) for i in range(101)])["error"]
    assert "must not be empty" in fn([])["error"]
    _nothing_written(anki)
    assert fn([spec(i) for i in range(100)])["added"] == 100


def test_add_cards_all_or_nothing_on_duplicate(anki, tool):
    anki.add_note("Default", fields={"Front": "dup"})
    n_before = len(anki.notes)
    r = tool("anki_add_cards")([NoteSpec(deck="Default", fields={"Front": "new"}),
                                NoteSpec(deck="Default", fields={"Front": "dup"})])
    assert "error" in r and len(anki.notes) == n_before


def test_update_card_unknown_field_writes_nothing(anki, tool):
    nid, _ = anki.add_note(fields={"Front": "a"})
    r = tool("anki_update_card")(nid, fields={"Nope": "x"})
    assert "Unknown field" in r["error"]
    _nothing_written(anki)


def test_update_card_missing_note(anki, tool):
    assert "not found" in tool("anki_update_card")(999, front="x")["error"]
    _nothing_written(anki)


def test_update_card_requires_something(anki, tool):
    nid, _ = anki.add_note()
    assert "error" in tool("anki_update_card")(nid)
    assert anki.calls == []


def test_update_card_front_conflict(anki, tool):
    nid, _ = anki.add_note()
    assert "error" in tool("anki_update_card")(nid, front="a", fields={"Front": "b"})
    _nothing_written(anki)


def test_update_card_only_named_fields_change(anki, tool):
    nid, _ = anki.add_note(fields={"Front": "a", "Back": "b"})
    tool("anki_update_card")(nid, back="B", tags="x y")
    n = anki.notes[nid]
    assert n["fields"] == {"Front": "a", "Back": "B"} and n["tags"] == ["x", "y"]


def test_can_add_cards_never_writes(anki, tool):
    anki.add_note("Default", fields={"Front": "dup"})
    r = tool("anki_can_add_cards")([NoteSpec(deck="Default", fields={"Front": "dup"}),
                                    NoteSpec(deck="Default", fields={"Front": "fresh"}),
                                    NoteSpec(deck="Missing", fields={"Front": "z"})])
    assert r["failed"] == 2 and not r["all_ok"]
    assert [x["can_add"] for x in r["results"]] == [False, True, False]
    assert not anki.writes()


def test_can_add_cards_validates_before_asking_anki(anki, tool):
    assert "error" in tool("anki_can_add_cards")([NoteSpec(deck="Default", fields={"Zzz": "a"})])
    assert "canAddNotesWithErrorDetail" not in anki.actions()


def test_create_deck_blank_rejected(anki, tool):
    assert "error" in tool("anki_create_deck")("  ")
    assert not anki.calls


def test_set_limits_requires_a_value(anki, tool):
    assert "error" in tool("anki_set_deck_preset_limits")("Default")
    assert not anki.calls


# ---- explicit null through FastMCP's real argument validation ----------------------------
REQUIRED_SAMPLES = {"search_query": "deck:D", "deck": "D", "note_id": 1, "model": "Basic", "days": "0",
                    "notes": [{"deck": "Default", "fields": {"Front": "a"}}]}


def _optional_params(nullable_wanted):
    for t in asyncio.run(mcp.list_tools()):
        req = t.inputSchema.get("required", [])
        for p, s in t.inputSchema.get("properties", {}).items():
            if p in req:
                continue
            nullable = any(o.get("type") == "null" for o in s.get("anyOf", []))
            if nullable == nullable_wanted and p != "dry_run":
                yield pytest.param(t, p, id=f"{t.name}.{p}")


def _args(t, p):
    args = {r: REQUIRED_SAMPLES[r] for r in t.inputSchema.get("required", [])}
    args[p] = None
    return args


@pytest.mark.parametrize("t,p", list(_optional_params(True)))
def test_explicit_null_validates_for_nullable_optionals(anki, call, t, p):
    call(t.name, _args(t, p))  # ToolError here means validation rejected the null


def test_no_optional_param_rejects_null():
    assert list(_optional_params(False)) == []


@pytest.mark.parametrize("name,args", [
    ("anki_delete_note", {"note_id": 1}),
    ("anki_delete_deck", {"deck": "x"}),
    ("anki_reschedule_cards", {"search_query": "a", "days": "0"}),
])
def test_dry_run_null_is_rejected_not_coerced(anki, call, name, args):
    with pytest.raises(ToolError):
        call(name, {**args, "dry_run": None})
    assert not anki.calls
