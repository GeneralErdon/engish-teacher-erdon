"""`vt-api-openapi [PATH]`: write the api's OpenAPI schema without starting a server.

`just types` turns it into the UI's TypeScript types (`apps/desktop/src/generated/api.d.ts`);
CI regenerates both and fails if the committed copies are stale.
"""

import json
import sys
from pathlib import Path

from vt_api.config import Settings
from vt_api.main import create_app


def schema_json() -> str:
    """Deterministic: sorted keys and a trailing newline, so the file only changes with the API."""
    schema = create_app(Settings(_env_file=None)).openapi()
    return json.dumps(schema, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def main(argv: list[str] | None = None) -> None:
    args = sys.argv[1:] if argv is None else argv
    if args:
        Path(args[0]).write_text(schema_json(), encoding="utf-8")
    else:
        sys.stdout.write(schema_json())


if __name__ == "__main__":
    main()
