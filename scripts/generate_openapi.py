"""Generate an OpenAPI document directly from the FastAPI application."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import app


def main() -> None:
    output_path = Path(__file__).resolve().parents[1] / "openapi.json"
    schema = app.openapi()
    output_path.write_text(json.dumps(schema, indent=2))
    print(f"OpenAPI document written to {output_path}")


if __name__ == "__main__":
    main()
