"""Client transport, logging, and CLI entry-point tests."""
import json
import logging
import sys
import urllib.error
import urllib.request

import pytest

import mcp_anki.anki as anki_mod
import mcp_anki.main as main_mod


def _capture_payloads(anki, monkeypatch):
    captured = []
    orig = anki.urlopen

    def capture(req, timeout=None):
        captured.append(json.loads(req.data))
        return orig(req, timeout=timeout)

    monkeypatch.setattr(urllib.request, "urlopen", capture)
    return captured


@pytest.mark.parametrize("key", [None, "secret-token"])
def test_anki_request_key_handling(anki, monkeypatch, key):
    captured = _capture_payloads(anki, monkeypatch)
    monkeypatch.setattr(anki_mod, "ANKI_CONNECT_KEY", key)
    anki_mod.anki_request("version")
    if key is None:
        assert "key" not in captured[0]
    else:
        assert captured[0]["key"] == key


def test_logged_tool_logs_positional_args_and_kwargs(anki, caplog, tool):
    with caplog.at_level(logging.INFO, logger="mcp_tools"):
        tool("anki_create_deck")("PositionalDeck")
    call_lines = [r.getMessage() for r in caplog.records if "CALL anki_create_deck" in r.getMessage()]
    assert call_lines and "('PositionalDeck',)" in call_lines[-1]


def test_cli_check_succeeds_when_reachable(anki, monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["mcp-anki", "--check"])
    with pytest.raises(SystemExit) as exc:
        main_mod.main()
    assert exc.value.code == 0
    assert "API version 6" in capsys.readouterr().out


def test_cli_check_fails_when_unreachable(monkeypatch, capsys):
    def refuse(*a, **k):
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(urllib.request, "urlopen", refuse)
    monkeypatch.setattr(sys, "argv", ["mcp-anki", "--check"])
    with pytest.raises(SystemExit) as exc:
        main_mod.main()
    assert exc.value.code == 1
    assert "unreachable" in capsys.readouterr().out


def test_cli_runs_mcp_without_check_flag(monkeypatch):
    ran = []
    monkeypatch.setattr(sys, "argv", ["mcp-anki"])
    monkeypatch.setattr(main_mod.mcp, "run", lambda: ran.append(True))
    main_mod.main()
    assert ran == [True]
