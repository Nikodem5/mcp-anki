import json
import logging
import urllib.request
from functools import wraps

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("chunk-factory")

_logger = logging.getLogger("mcp_tools")
_logger.setLevel(logging.DEBUG)
_handler = logging.FileHandler("mcp_tools.log", encoding="utf-8")
_handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
_logger.addHandler(_handler)


def logged_tool(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        _logger.info(f"CALL {fn.__name__} | args={kwargs}")
        try:
            result = fn(*args, **kwargs)
            _logger.info(f"  OK {fn.__name__} | result={str(result)[:200]}")
            return result
        except Exception as e:
            _logger.error(f" ERR {fn.__name__} | {e}")
            raise
    return wrapper


def anki_request(action: str, **params):
    payload = {"action": action, "version": 6}
    if params:
        payload["params"] = params
    req = urllib.request.Request(
        "http://localhost:8765",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        result = json.loads(resp.read())
    if result.get("error"):
        raise Exception(f"AnkiConnect: {result['error']}")
    return result.get("result")


@mcp.tool()
@logged_tool
def hello() -> str:
    """Ping to verify the MCP server is running."""
    return "Chunk Factory MCP server is running."


@mcp.tool()
@logged_tool
def test_anki_connection() -> str:
    """Check whether AnkiConnect is reachable."""
    try:
        version = anki_request("version")
        return json.dumps({"connected": True, "version": version})
    except Exception as e:
        return json.dumps({"connected": False, "error": str(e)})


if __name__ == "__main__":
    mcp.run()
