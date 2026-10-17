"""Safety invariants: nothing destructive is sent unless explicitly asked for."""
import pytest


# ---- dry_run ----------------------------------------------------------------------------
def test_delete_note_dry_run_default_never_writes(anki, tool):
    nid, _ = anki.add_note()
    r = tool("anki_delete_note")(nid)
    assert r["dry_run"] is True and "deleteNotes" not in anki.actions()
    assert nid in anki.notes


def test_delete_note_real_sends_delete(anki, tool):
    nid, _ = anki.add_note()
    tool("anki_delete_note")(nid, dry_run=False)
    assert anki.of("deleteNotes") == [{"notes": [nid]}]
    assert nid not in anki.notes


def test_delete_deck_dry_run_default_never_writes(anki, tool):
    anki.add_note("Doomed")
    anki.add_note("Doomed::Sub")
    r = tool("anki_delete_deck")("Doomed")
    assert r["dry_run"] is True and r["cards_affected"] == 2
    assert r["decks_affected"] == ["Doomed", "Doomed::Sub"]
    assert "deleteDecks" not in anki.actions()


def test_delete_deck_real_sends_cardstoo(anki, tool):
    anki.add_note("Doomed")
    tool("anki_delete_deck")("Doomed", dry_run=False)
    assert anki.of("deleteDecks") == [{"decks": ["Doomed"], "cardsToo": True}]
    assert "Doomed" not in anki.decks


def test_reschedule_dry_run_default_never_writes(anki, tool):
    anki.add_note("D")
    r = tool("anki_reschedule_cards")("deck:D", "0")
    assert r["dry_run"] is True and r["would_reschedule"] == 1
    assert "setDueDate" not in anki.actions()


def test_reschedule_real_sends_setduedate(anki, tool):
    _, cid = anki.add_note("D")
    r = tool("anki_reschedule_cards")("deck:D", "3-7", dry_run=False)
    assert anki.of("setDueDate") == [{"cards": [cid], "days": "3-7"}]
    assert r["rescheduled"] == 1


def test_reschedule_real_with_no_matches_sends_nothing(anki, tool):
    anki.add_deck("Empty")
    r = tool("anki_reschedule_cards")("deck:Empty", "0", dry_run=False)
    assert r["rescheduled"] == 0 and "setDueDate" not in anki.actions()


# ---- empty-query guard ------------------------------------------------------------------
BLANKS = ["", " ", "   ", "\t\n"]


@pytest.mark.parametrize("q", BLANKS)
@pytest.mark.parametrize("name,key,extra", [
    ("anki_get_cards", "search_query", {}),
    ("anki_get_notes", "search_query", {}),
    ("anki_check_exists", "search_query", {}),
    ("anki_reschedule_cards", "search_query", {"days": "0"}),
    ("anki_move_cards", "query", {"deck": "Default"}),
])
def test_blank_query_never_reaches_find(anki, tool, name, key, extra, q):
    r = tool(name)(**{key: q}, **extra)
    assert "error" in r
    assert not {"findCards", "findNotes"} & set(anki.actions())


@pytest.mark.parametrize("q", ["deck:*", ' "deck:*" ', "*", "DECK:*"])
def test_guard_rejects_whole_collection_wildcards(anki, tool, q):
    anki.add_note("A")
    assert "error" in tool("anki_get_cards")(q)
    assert not {"findCards", "findNotes"} & set(anki.actions())


# ---- missing-deck guards ----------------------------------------------------------------
def test_move_into_missing_deck_never_changes_deck(anki, tool):
    _, cid = anki.add_note("Src")
    r = tool("anki_move_cards")("Nope", card_ids=[cid])
    assert "error" in r and "changeDeck" not in anki.actions()
    assert "Nope" not in anki.decks and anki.cards[cid]["deck"] == "Src"


def test_move_cards_moves_and_reports_sources(anki, tool):
    _, cid = anki.add_note("Src")
    anki.add_deck("Dst")
    r = tool("anki_move_cards")("Dst", card_ids=[cid])
    assert r["moved"] == 1 and r["moved_from"] == {"Src": 1}


def test_move_cards_requires_exactly_one_selector(anki, tool):
    anki.add_deck("Dst")
    assert "error" in tool("anki_move_cards")("Dst")
    assert "error" in tool("anki_move_cards")("Dst", card_ids=[1], query="deck:Dst")
    assert "changeDeck" not in anki.actions()


def test_move_cards_limit_refuses(anki, tool):
    anki.add_deck("Dst")
    for _ in range(3):
        anki.add_note("Src")
    r = tool("anki_move_cards")("Dst", query="deck:Src", limit=2)
    assert "error" in r and "changeDeck" not in anki.actions()


def test_deck_stats_missing_deck_never_sends_getdeckstats(anki, tool):
    r = tool("anki_get_deck_stats")("Typo")
    assert "error" in r
    assert "getDeckStats" not in anki.actions() and "Typo" not in anki.decks


def test_delete_deck_refuses_default(anki, tool):
    r = tool("anki_delete_deck")("Default", dry_run=False)
    assert "error" in r and "deleteDecks" not in anki.actions()


def test_delete_deck_refuses_missing(anki, tool):
    r = tool("anki_delete_deck")("Ghost", dry_run=False)
    assert "error" in r and "deleteDecks" not in anki.actions()


def test_delete_deck_prefix_does_not_match_sibling(anki, tool):
    anki.add_note("Foo")
    anki.add_note("Foobar")
    r = tool("anki_delete_deck")("Foo")
    assert r["decks_affected"] == ["Foo"] and r["cards_affected"] == 1
