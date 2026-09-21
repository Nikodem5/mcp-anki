import json
import logging
import urllib.request
from functools import wraps

from .config import ANKI_CONNECT_KEY, ANKI_CONNECT_URL, MCP_ANKI_LOG

logger = logging.getLogger("mcp_tools")
logger.setLevel(logging.DEBUG)
_handler = logging.FileHandler(MCP_ANKI_LOG, encoding="utf-8")
_handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
logger.addHandler(_handler)


def anki_request(action: str, **params):
    # findCards("") / findNotes("") return the entire collection instead of erroring, so a
    # blank query is rejected here once rather than in every tool that takes a search string.
    if "query" in params and not (params["query"] or "").strip():
        raise ValueError("query must not be empty or whitespace-only")
    payload = {"action": action, "version": 6}
    if params:
        payload["params"] = params
    if ANKI_CONNECT_KEY:
        payload["key"] = ANKI_CONNECT_KEY
    # 127.0.0.1, not localhost: Windows resolves localhost to ::1 first, and AnkiConnect
    # binds IPv4 only (its webBindAddress default is 127.0.0.1), so every request through
    # "localhost" burns ~2s on a refused IPv6 attempt before falling back. Measured
    # 2026-09-19: 2.06s per call via localhost vs 0.03s via 127.0.0.1.
    req = urllib.request.Request(
        ANKI_CONNECT_URL,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        result = json.loads(resp.read())
    if result.get("error"):
        raise Exception(f"AnkiConnect: {result['error']}")
    return result.get("result")


def logged_tool(fn):
    """Log every call and its outcome, and turn an exception into the tool's error payload.

    This is the only place a tool's exception is caught: individual tools raise on failure
    (a validation error, an AnkiConnect error) instead of catching it themselves, so a real
    failure always produces an ERR log line instead of silently reporting OK.
    """
    @wraps(fn)
    def wrapper(*args, **kwargs):
        logger.info(f"CALL {fn.__name__} | args={args} kwargs={kwargs}")
        try:
            result = fn(*args, **kwargs)
            logger.info(f"  OK {fn.__name__} | result={str(result)[:200]}")
            return result
        except Exception as e:
            logger.error(f" ERR {fn.__name__} | {e}")
            return {"error": str(e)}
    return wrapper
