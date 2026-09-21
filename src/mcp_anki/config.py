import os

# 127.0.0.1, never localhost: see anki.py for why.
ANKI_CONNECT_URL = os.environ.get("ANKI_CONNECT_URL", "http://127.0.0.1:8765")
ANKI_CONNECT_KEY = os.environ.get("ANKI_CONNECT_KEY")
MCP_ANKI_LOG = os.environ.get("MCP_ANKI_LOG", "mcp_tools.log")
