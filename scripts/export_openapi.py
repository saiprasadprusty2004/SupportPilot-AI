"""Export the API without starting workers, seeding data, or contacting providers."""

import json
import os
from pathlib import Path

os.environ.setdefault("DEMO_MODE", "true")
os.environ.setdefault("SUPPORTPILOT_TESTING", "1")
from app.main import app

target = Path(__file__).resolve().parents[1] / "backend" / "openapi.json"
target.write_text(
    json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n", encoding="utf-8"
)
print(f"Exported {len(app.routes)} routes to {target.name}")
