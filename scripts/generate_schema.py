#!/usr/bin/env python3
"""
Generate config.schema.json from the Pydantic model in src/config_schema.py.

Run this script whenever you change the ConfigModel to regenerate the JSON Schema:
    python scripts/generate_schema.py
"""

import sys
from pathlib import Path

# Add project root to sys.path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.config_schema import generate_json_schema  # noqa: E402

if __name__ == "__main__":
    schema_path = project_root / "config.schema.json"
    generate_json_schema(schema_path)
    print(f"Generated JSON Schema at {schema_path}")
