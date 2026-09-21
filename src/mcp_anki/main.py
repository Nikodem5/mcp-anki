import sys

from .anki import anki_request
from .config import ANKI_CONNECT_URL
from .server import mcp


def main() -> None:
    if "--check" in sys.argv[1:]:
        sys.exit(_check())
    mcp.run()


def _check() -> int:
    try:
        version = anki_request("version")
    except Exception as e:
        print(f"AnkiConnect unreachable at {ANKI_CONNECT_URL}: {e}")
        return 1
    print(f"AnkiConnect reachable at {ANKI_CONNECT_URL} (API version {version})")
    return 0


if __name__ == "__main__":
    main()
