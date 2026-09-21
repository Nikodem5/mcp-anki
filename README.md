# mcp-anki

An MCP server that exposes Anki to an MCP client (Claude Desktop, Claude Code) through the
[AnkiConnect](https://ankiweb.net/shared/info/2055492159) add-on.

Anki is the only data store, the server keeps no state of its own.

## Requirements

- Python 3.13+ and [uv](https://docs.astral.sh/uv/)
- Anki Desktop running, with AnkiConnect (add-on code `2055492159`) on `127.0.0.1:8765`

## Run

```bash
uv sync
uv run mcp-anki --check   # confirm AnkiConnect is reachable before wiring up a client
uv run mcp-anki
```

Claude Desktop config (`%APPDATA%\Claude\claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "mcp-anki": {
      "command": "FULL_PATH_TO_UV",
      "args": ["--directory", "FULL_PATH_TO_PROJECT", "run", "mcp-anki"]
    }
  }
}
```

Optional environment variables:

| Variable | Default | Purpose |
|---|---|---|
| `ANKI_CONNECT_URL` | `http://127.0.0.1:8765` | Where AnkiConnect is listening |
| `ANKI_CONNECT_KEY` | unset | API key, if AnkiConnect's `requestPermission` requires one |
| `MCP_ANKI_LOG` | `mcp_tools.log` | Path to the call log |

Anki has to be open for every tool to work.

## Tools

| Tool | Purpose |
|---|---|
| `test_anki_connection` | Confirm AnkiConnect is reachable |
| `anki_check_exists` | Search for existing notes before creating a duplicate |
| `anki_add_card` | Create a Basic card in a deck |
| `anki_get_notes` | Fetch fields, tags, and deck for notes matching a query |
| `anki_update_card` | Update front, back, and/or tags of a note |
| `anki_delete_note` | Delete a note and its cards |
| `anki_reschedule_cards` | Move the due date of every card matching a query; previews by default |
| `anki_list_decks` | List every deck name in the collection |
| `anki_get_deck_preset_limits` | Read new/day and review/day from the deck's Preset |
| `anki_set_deck_preset_limits` | Write those limits, cloning a shared Preset first |
| `anki_get_deck_stats` | Today's actual new/learn/review counts from the scheduler |
| `anki_sync` | Sync the collection with AnkiWeb |

Calls are logged to `mcp_tools.log` with arguments and results.

## Deck limits: the tier problem

Anki applies daily limits in three tiers, highest precedence first:

```
Today only  >  This deck  >  Preset
```

AnkiConnect can only read and write the **Preset** tier. If a deck has a "This deck" or
"Today only" override set in Deck Options, `anki_set_deck_preset_limits` will report success
and change the Preset while the app keeps showing the old numbers — the override wins, and
nothing in the API can see it. Clear it by hand in Anki.

`anki_get_deck_stats` reads what the scheduler actually computed for today, so use it to check
whether a limit change took effect.

When the limit tiers won't cooperate, `anki_reschedule_cards` goes around them: instead of
capping how many cards a day shows, it moves the cards themselves. `deck:"HSK 4" is:due` with
`days="1-14"` spreads a backlog of 220 due cards over the next two weeks at roughly 16 a day.
It previews by default (`dry_run` is `True`); applying it overwrites due dates irreversibly,
with Ctrl+Z in the Anki app as the only undo.

## License

MIT
