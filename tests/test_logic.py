"""Branching logic in the deck and card tools."""
import pytest


# ---- anki_set_deck_preset_limits ---------------------------------------------------------
def test_set_limits_unshared_does_not_clone(anki, tool):
    anki.add_note("A")
    anki.configs[2] = {"id": 2, "name": "Solo", "new": {"perDay": 20}, "rev": {"perDay": 200}}
    anki.deck_config["A"] = 2
    r = tool("anki_set_deck_preset_limits")("A", new_per_day=5)
    assert r["cloned_dedicated_config"] is False and r["was_shared_with"] == []
    assert not anki.of("cloneDeckConfigId") and not anki.of("setDeckConfigId")
    assert anki.configs[2]["new"]["perDay"] == 5 and anki.configs[2]["rev"]["perDay"] == 200


def test_set_limits_clones_when_preset_is_shared(anki, tool):
    anki.add_note("A")
    anki.add_note("B")
    r = tool("anki_set_deck_preset_limits")("A", new_per_day=5, review_per_day=50)
    assert r["cloned_dedicated_config"] is True and "B" in r["was_shared_with"]
    new_id = anki.deck_config["A"]
    assert new_id != 1 and anki.of("cloneDeckConfigId") == [{"name": "A (dedicated)", "cloneFrom": "1"}]
    assert anki.of("saveDeckConfig")[0]["config"]["id"] == new_id
    assert anki.configs[new_id]["new"]["perDay"] == 5 and anki.configs[new_id]["rev"]["perDay"] == 50
    # the sibling's preset is untouched
    assert anki.configs[1]["new"]["perDay"] == 20 and "B" not in anki.deck_config


def test_set_limits_missing_deck(anki, tool):
    r = tool("anki_set_deck_preset_limits")("Nope", new_per_day=5)
    assert "error" in r and "saveDeckConfig" not in anki.actions()


def test_get_preset_limits_reports_sharing(anki, tool):
    anki.add_deck("A"); anki.add_deck("B")
    r = tool("anki_get_deck_preset_limits")("A")
    assert sorted(r["shared_with"]) == ["B", "Default"] and r["new_per_day"] == 20
    assert "error" in tool("anki_get_deck_preset_limits")("Nope")


# ---- override_suspected heuristic --------------------------------------------------------
def _setup_new_cards(anki, n, deck="A"):
    for _ in range(n):
        anki.add_note(deck)


def test_override_suspected_positive(anki, tool):
    _setup_new_cards(anki, 20)
    anki.stats_override["A"] = (3, 0)  # scheduler shows 3 although limit 10 and 20 available
    r = tool("anki_set_deck_preset_limits")("A", new_per_day=10)
    assert r["override_suspected"] == ["new_per_day"] and "override_note" in r
    assert r["live_check"] == {"new_count": 3, "review_count": 0}


def test_override_suspected_negative(anki, tool):
    _setup_new_cards(anki, 20)
    anki.stats_override["A"] = (10, 0)
    assert tool("anki_set_deck_preset_limits")("A", new_per_day=10)["override_suspected"] is False


def test_override_not_suspected_when_backlog_smaller_than_limit(anki, tool):
    _setup_new_cards(anki, 4)
    assert tool("anki_set_deck_preset_limits")("A", new_per_day=10)["override_suspected"] is False


def test_override_suspected_reviews(anki, tool):
    for _ in range(8):
        anki.add_note("A", queue=2, type=2, is_due=True)
    anki.stats_override["A"] = (0, 2)
    r = tool("anki_set_deck_preset_limits")("A", review_per_day=5)
    assert r["override_suspected"] == ["review_per_day"]


def test_override_only_checks_fields_that_were_set(anki, tool):
    _setup_new_cards(anki, 20)
    anki.stats_override["A"] = (0, 0)
    assert tool("anki_set_deck_preset_limits")("A", review_per_day=5)["override_suspected"] is False


def test_override_check_skipped_when_stats_unavailable(anki, tool):
    anki.add_deck("A")  # no cards -> getDeckStats returns {}
    r = tool("anki_set_deck_preset_limits")("A", new_per_day=5)
    assert r["live_check"] is None and "override_suspected" not in r


def test_override_undetermined_when_deck_has_subdecks(anki, tool):
    anki.add_deck("A")
    _setup_new_cards(anki, 20, "A::child")
    anki.stats_override["A"] = (2, 0)  # child preset allows only 2/day
    r = tool("anki_set_deck_preset_limits")("A", new_per_day=10)
    assert r["override_suspected"] is None and "subdecks" in r["override_note"]


# ---- anki_get_cards ----------------------------------------------------------------------
def test_get_cards_decoding(anki, tool):
    anki.add_note("D", fields={"Front": "<b>hi</b> [sound:x.mp3] &amp; you"}, type=2, queue=2, due=900,
                  ivl=30, factor=2500, reps=5, lapses=1, flags=0b1010)
    c = tool("anki_get_cards")("deck:D")["cards"][0]
    assert (c["type"], c["queue"], c["interval_days"], c["ease_percent"]) == ("review", "review", 30, 250)
    assert c["flag"] == 2 and c["due_kind"].startswith("day number")
    assert c["fields_preview"] == {"Front": "hi & you"}


def test_get_cards_new_and_unreviewed(anki, tool):
    anki.add_note("D", due=7)
    c = tool("anki_get_cards")("deck:D")["cards"][0]
    assert c["type"] == "new" and c["ease_percent"] is None
    assert c["due_kind"].startswith("new-card position")


def test_get_cards_learning_due_is_epoch(anki, tool):
    anki.add_note("D", type=1, queue=1, due=0)
    c = tool("anki_get_cards")("deck:D")["cards"][0]
    assert c["due_at_utc"].startswith("1970-01-01")


def test_get_cards_suspended_uses_type_for_due_unit(anki, tool):
    anki.add_note("D", type=2, queue=-1, due=500)
    c = tool("anki_get_cards")("deck:D")["cards"][0]
    assert c["queue"] == "suspended" and c["due_kind"].startswith("day number")


def test_get_cards_matched_vs_returned(anki, tool):
    for _ in range(5):
        anki.add_note("D")
    r = tool("anki_get_cards")("deck:D", limit=2)
    assert (r["matched"], r["returned"]) == (5, 2)
    assert len(anki.of("cardsInfo")[0]["cards"]) == 2


def test_get_cards_no_match_skips_cardsinfo(anki, tool):
    anki.add_deck("D")
    assert tool("anki_get_cards")("deck:D") == {"matched": 0, "returned": 0, "cards": []}
    assert "cardsInfo" not in anki.actions()


def test_get_cards_drops_vanished_cards(anki, tool):
    anki.add_note("D")
    anki.a_cardsInfo = lambda cards: [{}]  # card deleted between findCards and cardsInfo
    r = tool("anki_get_cards")("deck:D")
    assert (r["matched"], r["returned"]) == (1, 0)


def test_get_cards_limit_bounds_enforced_by_schema(anki, call):
    from mcp.server.fastmcp.exceptions import ToolError
    for bad in (0, 101):
        with pytest.raises(ToolError):
            call("anki_get_cards", {"search_query": "deck:D", "limit": bad})


# ---- anki_get_deck_stats -----------------------------------------------------------------
def test_deck_stats_resolves_basename_for_nested_deck(anki, tool):
    anki.add_note("Mandarin::e. HSK4")
    r = tool("anki_get_deck_stats")("Mandarin::e. HSK4")
    assert r["deck"] == "Mandarin::e. HSK4" and r["name"] == "e. HSK4" and r["new_count"] == 1


def test_deck_stats_matches_by_name_when_multiple_entries(anki, tool):
    anki.add_note("P::kid")
    anki.a_getDeckStats = lambda decks: {
        "1": {"name": "other", "new_count": 9}, "2": {"name": "kid", "new_count": 4}}
    assert tool("anki_get_deck_stats")("P::kid")["new_count"] == 4


def test_deck_stats_ambiguous_returns_raw_stats(anki, tool):
    anki.add_note("P::kid")
    raw = {"1": {"name": "x"}, "2": {"name": "y"}}
    anki.a_getDeckStats = lambda decks: raw
    assert tool("anki_get_deck_stats")("P::kid") == raw


def test_deck_stats_empty_deck(anki, tool):
    anki.add_deck("E")
    assert "no stats" in tool("anki_get_deck_stats")("E")["error"]


# ---- small tools -------------------------------------------------------------------------
def test_decks_with_ids_truncation(anki, tool):
    for i in range(3):
        anki.add_deck(f"d{i}")
    r = tool("anki_list_decks_with_ids")(limit=2)
    assert r["total"] == 4 and len(r["decks"]) == 2 and r["truncated"] is True


def test_create_deck_reports_created(anki, tool):
    assert tool("anki_create_deck")("N")["created"] is True
    assert tool("anki_create_deck")("N")["created"] is False


def test_get_notes_deck_and_matched(anki, tool):
    anki.add_note("D", fields={"Front": "x"})
    anki.add_note("D", fields={"Front": "y"})
    r = tool("anki_get_notes")("deck:D", limit=1)
    assert (r["matched"], r["returned"]) == (2, 1) and r["notes"][0]["deck"] == "D"


def test_delete_note_missing_errors(anki, tool):
    assert "error" in tool("anki_delete_note")(12345)
    assert "deleteNotes" not in anki.actions()


def test_models_tools(anki, tool):
    assert tool("anki_list_models")()["models"] == ["Basic", "Cloze"]
    f = tool("anki_get_model_fields")("Basic")
    assert [x["name"] for x in f["fields"]] == ["Front", "Back"]


def test_connection_and_sync(anki, tool):
    assert tool("test_anki_connection")() == {"connected": True, "version": 6}
    assert tool("anki_sync")() == {"synced": True}
