"""Contract tests over every registered tool."""
import asyncio
import logging
import urllib.error
import urllib.request

import pytest

from conftest import mcp
from mcp_anki.tools.notes import NoteSpec

EXPECTED = {
    "anki_check_exists", "anki_add_card", "anki_add_cards", "anki_can_add_cards", "anki_get_notes",
    "anki_update_card", "anki_delete_note",
    "anki_list_models", "anki_get_model_fields",
    "anki_get_cards",
    "anki_list_decks", "anki_get_deck_preset_limits", "anki_set_deck_preset_limits",
    "anki_get_deck_stats", "anki_list_decks_with_ids", "anki_create_deck", "anki_move_cards",
    "anki_delete_deck",
    "anki_reschedule_cards",
    "test_anki_connection", "anki_sync",
}

TOOLS = asyncio.run(mcp.list_tools())

# Minimal valid arguments per tool, for forced-failure calls.
SAMPLE = {
    "anki_check_exists": {"search_query": "deck:D"},
    "anki_add_card": {"deck": "D", "front": "a"},
    "anki_add_cards": {"notes": [NoteSpec(deck="D", fields={"Front": "a"})]},
    "anki_can_add_cards": {"notes": [NoteSpec(deck="D", fields={"Front": "a"})]},
    "anki_get_notes": {"search_query": "deck:D"},
    "anki_update_card": {"note_id": 1, "front": "a"},
    "anki_delete_note": {"note_id": 1},
    "anki_list_models": {},
    "anki_get_model_fields": {"model": "Basic"},
    "anki_get_cards": {"search_query": "deck:D"},
    "anki_list_decks": {},
    "anki_get_deck_preset_limits": {"deck": "D"},
    "anki_set_deck_preset_limits": {"deck": "D", "new_per_day": 1},
    "anki_get_deck_stats": {"deck": "D"},
    "anki_list_decks_with_ids": {},
    "anki_create_deck": {"deck": "D"},
    "anki_move_cards": {"deck": "D", "query": "deck:D"},
    "anki_delete_deck": {"deck": "D"},
    "anki_reschedule_cards": {"search_query": "deck:D", "days": "0"},
    "test_anki_connection": {},
    "anki_sync": {},
}


def test_exact_tool_set():
    assert {t.name for t in TOOLS} == EXPECTED and len(TOOLS) == 21
    assert set(SAMPLE) == EXPECTED


NO_ANNOTATIONS: set[str] = set()


@pytest.mark.parametrize("t", [
    pytest.param(t, id=t.name, marks=pytest.mark.xfail(
        strict=True, reason="finding: registered without ToolAnnotations, though AGENTS.md says "
                            "every tool declares them")) if t.name in NO_ANNOTATIONS else pytest.param(t, id=t.name)
    for t in TOOLS])
def test_has_annotations(t):
    assert t.annotations is not None, f"{t.name} has no ToolAnnotations"


@pytest.mark.parametrize("t", TOOLS, ids=lambda t: t.name)
def test_has_description(t):
    assert t.description


def _walk_props(schema):
    for name, s in schema.get("properties", {}).items():
        yield name, s


@pytest.mark.parametrize("t", TOOLS, ids=lambda t: t.name)
def test_every_parameter_has_description(t):
    missing = [n for n, s in _walk_props(t.inputSchema) if not s.get("description")]
    assert not missing, f"{t.name}: no description for {missing}"


def test_noteSpec_subfields_have_descriptions():
    defs = next(t for t in TOOLS if t.name == "anki_add_cards").inputSchema["$defs"]["NoteSpec"]
    assert all(s.get("description") for s in defs["properties"].values())


@pytest.mark.parametrize("t", [t for t in TOOLS if t.annotations and t.annotations.destructiveHint],
                         ids=lambda t: t.name)
def test_destructive_tools_default_to_dry_run(t):
    p = t.inputSchema["properties"].get("dry_run")
    assert p is not None and p.get("default") is True and p["type"] == "boolean"


def test_destructive_tool_inventory():
    assert {t.name for t in TOOLS if t.annotations and t.annotations.destructiveHint} == {
        "anki_delete_note", "anki_delete_deck", "anki_reschedule_cards"}


@pytest.mark.parametrize("t", TOOLS, ids=lambda t: t.name)
def test_no_bare_string_with_null_default(t):
    bad = [n for n, s in _walk_props(t.inputSchema)
           if s.get("type") == "string" and "default" in s and s["default"] is None]
    assert not bad


@pytest.fixture
def anki_down(monkeypatch):
    def refuse(*a, **k):
        raise urllib.error.URLError("connection refused (simulated)")
    monkeypatch.setattr(urllib.request, "urlopen", refuse)


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_tool_returns_error_dict_and_logs_err_on_failure(anki_down, caplog, call, name):
    with caplog.at_level(logging.DEBUG, logger="mcp_tools"):
        result = call(name, SAMPLE[name])
    assert isinstance(result, dict) and "error" in result
    assert any(r.levelno == logging.ERROR and name in r.getMessage() for r in caplog.records)


@pytest.mark.parametrize("name", ["anki_list_models", "anki_list_decks", "anki_sync"])
def test_success_returns_dict_and_logs_ok(anki, caplog, call, name):
    with caplog.at_level(logging.DEBUG, logger="mcp_tools"):
        result = call(name)
    assert isinstance(result, dict) and "error" not in result
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]


def test_connection_failure_shape(anki_down, tool):
    r = tool("test_anki_connection")()
    assert r["connected"] is False and r["error"]


def test_ankiconnect_error_is_surfaced(anki, tool):
    anki.raise_on["deckNames"] = "boom"
    assert tool("anki_list_decks")() == {"error": "AnkiConnect: boom"}


# ---- harness self-checks -----------------------------------------------------------------
def test_unpatched_transport_fails_loudly():
    from conftest import RealAnkiAccessError
    from mcp_anki.anki import anki_request
    with pytest.raises(RealAnkiAccessError):
        anki_request("version")
