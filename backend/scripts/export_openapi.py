"""Export the FastAPI contract used to generate the browser TypeScript types."""

from __future__ import annotations

import json
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config import Environment, Settings  # noqa: E402
from app.main import create_app  # noqa: E402


def main() -> None:
    application = create_app(Settings(environment=Environment.TEST))
    destination = BACKEND_ROOT / "openapi.json"
    destination.write_text(
        json.dumps(application.openapi(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(destination)


if __name__ == "__main__":
    main()
