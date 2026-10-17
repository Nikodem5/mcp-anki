"""Test harness: an in-memory AnkiConnect (FakeAnki) behind the real anki_request.

The fake sits at the transport (urllib.request.urlopen), not at anki_request, so the real
anki_request runs in every test: its empty-query guard, payload shaping and error handling
are exercised. Every module imports anki_request by name, but they all share the one function
object, so replacing the transport covers them all with a single patch.

An autouse fixture makes any call that is not routed to a FakeAnki fail loudly, so a test
can never reach a real Anki on 127.0.0.1:8765.
"""
import asyncio
import io
import json
import os
import tempfile

# Must be set before mcp_anki is imported: anki.py opens its log file at import time.
os.environ["MCP_ANKI_LOG"] = os.path.join(tempfile.mkdtemp(prefix="mcp_anki_test_"), "test.log")
os.environ.pop("ANKI_CONNECT_KEY", None)

import socket  # noqa: E402
import urllib.request  # noqa: E402

import pytest  # noqa: E402

from mcp_anki.server import mcp  # noqa: E402


class RealAnkiAccessError(AssertionError):
    pass


@pytest.fixture(autouse=True)
def _no_real_network(monkeypatch):
    def boom(*a, **k):
        raise RealAnkiAccessError("test tried to reach a real Anki / the network without FakeAnki")

    monkeypatch.setattr(urllib.request, "urlopen", boom)
    real_connect = socket.socket.connect

    def guarded_connect(self, address, *a, **k):
        # asyncio's self-pipe connects to a random loopback port, so only 8765 and
        # non-loopback addresses are refused.
        if not (isinstance(address, tuple) and address[0] in ("127.0.0.1", "::1") and address[1] != 8765):
            boom()
        return real_connect(self, address, *a, **k)

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)


class AnkiError(Exception):
    pass


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _unescape_deck(s):
    out, i = [], 0
    while i < len(s):
        if s[i] == "\\" and i + 1 < len(s):
            i += 1
        out.append(s[i])
        i += 1
    return "".join(out)


class FakeAnki:
    def __init__(self):
        self.calls = []  # (action, params)
        self.decks = {"Default": 1}
        self._next = 1000
        self.models = {"Basic": ["Front", "Back"], "Cloze": ["Text", "Back Extra"]}
        self.notes = {}  # id -> {model, fields, tags, cards}
        self.cards = {}  # id -> dict (see add_note)
        self.configs = {1: {"id": 1, "name": "Default", "new": {"perDay": 20}, "rev": {"perDay": 200}}}
        self.deck_config = {}  # deck name -> config id (default 1)
        self.stats_override = {}  # deck name -> (new_count, review_count)
        self.raise_on = {}  # action -> error message AnkiConnect should return

    # ---- test-side helpers -------------------------------------------------------------
    def _id(self):
        self._next += 1
        return self._next

    def add_deck(self, name):
        self.decks.setdefault(name, self._id())
        return self.decks[name]

    def add_note(self, deck="Default", model="Basic", fields=None, tags=(), **card):
        self.add_deck(deck)
        names = self.models[model]
        nid = self._id()
        fields = fields or {names[0]: f"front{nid}"}
        cid = self._id()
        self.notes[nid] = {"model": model, "fields": {n: fields.get(n, "") for n in names},
                           "tags": list(tags), "cards": [cid]}
        base = dict(note=nid, deck=deck, type=0, queue=0, due=1, ivl=0, factor=0, reps=0,
                    lapses=0, flags=0, is_due=False)
        base.update(card)
        self.cards[cid] = base
        return nid, cid

    def actions(self):
        return [a for a, _ in self.calls]

    def of(self, action):
        return [p for a, p in self.calls if a == action]

    def writes(self):
        return [a for a in self.actions() if a in WRITE_ACTIONS]

    # ---- transport ---------------------------------------------------------------------
    def urlopen(self, req, timeout=None):
        body = json.loads(req.data)
        action, params = body["action"], body.get("params", {})
        self.calls.append((action, params))
        try:
            if action in self.raise_on:
                raise AnkiError(self.raise_on[action])
            handler = getattr(self, "a_" + action, None)
            if handler is None:
                raise AnkiError(f"unsupported action in FakeAnki: {action}")
            out = {"result": handler(**params), "error": None}
        except AnkiError as e:
            out = {"result": None, "error": str(e)}
        return _Resp(json.dumps(out).encode())

    # ---- query matching (only what the tools emit) -------------------------------------
    def _match(self, query):
        ids = list(self.cards)
        for tok in _tokens(query):
            if tok.startswith("deck:"):
                d = _unescape_deck(tok[5:].strip('"'))
                if d == "*":
                    continue
                ids = [i for i in ids if self.cards[i]["deck"] == d or self.cards[i]["deck"].startswith(d + "::")]
            elif tok == "is:new":
                ids = [i for i in ids if self.cards[i]["queue"] == 0]
            elif tok == "is:due":
                ids = [i for i in ids if self.cards[i]["is_due"]]
            # any other token matches everything: FakeAnki is not a search engine
        return ids

    # ---- actions -----------------------------------------------------------------------
    def a_version(self):
        return 6

    def a_sync(self):
        return None

    def a_deckNames(self):
        return list(self.decks)

    def a_deckNamesAndIds(self):
        return dict(self.decks)

    def a_createDeck(self, deck):
        return self.add_deck(deck)

    def a_deleteDecks(self, decks, cardsToo=False):
        if not cardsToo:
            raise AnkiError("cardsToo must be true")
        for d in decks:
            for name in [n for n in self.decks if n == d or n.startswith(d + "::")]:
                del self.decks[name]
                for cid in [c for c, v in self.cards.items() if v["deck"] == name]:
                    nid = self.cards.pop(cid)["note"]
                    self.notes.pop(nid, None)

    def a_changeDeck(self, cards, deck):
        self.add_deck(deck)  # real changeDeck creates a missing target
        for c in cards:
            self.cards[c]["deck"] = deck

    def a_getDecks(self, cards):
        out = {}
        for c in cards:
            if c in self.cards:
                out.setdefault(self.cards[c]["deck"], []).append(c)
        return out

    def a_findCards(self, query):
        return self._match(query)

    def a_findNotes(self, query):
        return sorted({self.cards[c]["note"] for c in self._match(query)})

    def _note_info(self, nid):
        n = self.notes.get(nid)
        if not n:
            return {}
        return {"noteId": nid, "modelName": n["model"], "tags": n["tags"], "cards": n["cards"],
                "fields": {k: {"value": v, "order": i} for i, (k, v) in enumerate(n["fields"].items())}}

    def a_notesInfo(self, notes):
        return [self._note_info(n) for n in notes]

    def a_cardsInfo(self, cards):
        out = []
        for cid in cards:
            c = self.cards.get(cid)
            if not c:
                out.append({})
                continue
            n = self.notes[c["note"]]
            out.append({"cardId": cid, "note": c["note"], "deckName": c["deck"], "modelName": n["model"],
                        "type": c["type"], "queue": c["queue"], "interval": c["ivl"],
                        "factor": c["factor"], "reps": c["reps"], "lapses": c["lapses"],
                        "flags": c["flags"], "due": c["due"],
                        "fields": {k: {"value": v, "order": i} for i, (k, v) in enumerate(n["fields"].items())}})
        return out

    def a_modelNames(self):
        return list(self.models)

    def a_modelFieldNames(self, modelName):
        return list(self.models[modelName])

    def a_modelFieldDescriptions(self, modelName):
        return ["" for _ in self.models[modelName]]

    def _can_add(self, note):
        if note["deckName"] not in self.decks:
            return "deck was not found: " + note["deckName"]
        names = self.models.get(note["modelName"])
        if names is None:
            return "model was not found: " + note["modelName"]
        first = note["fields"].get(names[0], "")
        if not first.strip():
            return "cannot create note because it is empty"
        for n in self.notes.values():  # first-field-only duplicate check, same model
            if n["model"] == note["modelName"] and n["fields"][names[0]] == first:
                return "cannot create note because it is a duplicate"
        return None

    def a_canAddNotesWithErrorDetail(self, notes):
        res = []
        for n in notes:
            e = self._can_add(n)
            res.append({"canAdd": True} if e is None else {"canAdd": False, "error": e})
        return res

    def _create(self, note):
        e = self._can_add(note)
        if e:
            raise AnkiError(e)
        nid, _ = self.add_note(note["deckName"], note["modelName"], note["fields"], note.get("tags", []))
        return nid

    def a_addNote(self, note):
        return self._create(note)

    def a_addNotes(self, notes):
        errs = [e for e in (self._can_add(n) for n in notes) if e]
        if errs:
            raise AnkiError(str(errs))
        return [self._create(n) for n in notes]

    def a_updateNote(self, note):
        n = self.notes[note["id"]]
        for k, v in note.get("fields", {}).items():
            if k in n["fields"]:  # quirk: unknown field names are silently ignored
                n["fields"][k] = v
        if "tags" in note:
            n["tags"] = note["tags"]

    a_updateNoteFields = a_updateNote

    def a_deleteNotes(self, notes):
        for nid in notes:
            for cid in self.notes.pop(nid)["cards"]:
                self.cards.pop(cid, None)

    def a_setDueDate(self, cards, days):
        return True

    # deck options
    def a_getDeckConfig(self, deck):
        if deck not in self.decks:
            return False
        return json.loads(json.dumps(self.configs[self.deck_config.get(deck, 1)]))

    def a_cloneDeckConfigId(self, name, cloneFrom):
        cfg = json.loads(json.dumps(self.configs[int(cloneFrom)]))
        cfg["id"], cfg["name"] = self._id(), name
        self.configs[cfg["id"]] = cfg
        return cfg["id"]

    def a_setDeckConfigId(self, decks, configId):
        for d in decks:
            self.deck_config[d] = configId
        return True

    def a_saveDeckConfig(self, config):
        self.configs[config["id"]] = config
        return True

    def a_getDeckStats(self, decks):
        out = {}
        for d in decks:
            did = self.add_deck(d)  # quirk: creates a missing deck
            ids = self._match(f'deck:"{d}"')
            if not ids:
                continue
            new, rev = self.stats_override.get(d) or (
                sum(self.cards[i]["queue"] == 0 for i in ids), sum(self.cards[i]["is_due"] for i in ids))
            out[str(did)] = {"deck_id": did, "name": d.split("::")[-1],  # quirk: basename
                             "new_count": new, "learn_count": 0, "review_count": rev,
                             "total_in_deck": len(ids)}
        return out


WRITE_ACTIONS = {"addNote", "addNotes", "updateNote", "updateNoteFields", "deleteNotes", "deleteDecks",
                 "changeDeck", "setDueDate", "createDeck", "saveDeckConfig", "setDeckConfigId",
                 "cloneDeckConfigId", "sync"}


def _tokens(q):
    toks, cur, inq = [], "", False
    for ch in q:
        if ch == '"' :
            inq = not inq
            cur += ch
        elif ch == " " and not inq:
            if cur:
                toks.append(cur)
            cur = ""
        else:
            cur += ch
    if cur:
        toks.append(cur)
    return toks


@pytest.fixture
def anki(monkeypatch):
    fake = FakeAnki()
    monkeypatch.setattr(urllib.request, "urlopen", fake.urlopen)
    return fake


@pytest.fixture
def tool():
    """Registered tool function by name, called directly (still wrapped by @logged_tool)."""
    def get(name):
        return mcp._tool_manager.get_tool(name).fn
    return get


@pytest.fixture
def call():
    """Call a tool through FastMCP (argument validation included); returns the dict result."""
    def run(name, args=None):
        return asyncio.run(mcp.call_tool(name, args or {}))[1]
    return run
