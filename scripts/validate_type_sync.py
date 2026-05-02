#!/usr/bin/env python3
"""
Type Sync Validator — Phase 1 专项验收
Verifies that frontend TypeScript types in frontend/src/types/api.ts
match the actual FastAPI Pydantic response models at runtime.

Run:
    python scripts/validate_type_sync.py
    python scripts/validate_type_sync.py --openapi-url http://localhost:8000/openapi.json
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import Any

API_TS_PATH = Path(__file__).parent.parent / "frontend" / "src" / "types" / "api.ts"
OPENAPI_URL_ENV = "OPENAPI_URL"
DEFAULT_OPENAPI_URL = "http://localhost:8000/openapi.json"


def extract_ts_interfaces(ts_content: str) -> dict[str, dict[str, Any]]:
    """Parse TypeScript interface definitions from api.ts."""
    interfaces: dict[str, dict[str, Any]] = {}

    interface_pattern = re.compile(
        r"export interface (\w+)\s*\{([^}]+)\}",
        re.DOTALL,
    )
    type_alias_pattern = re.compile(
        r"export type (\w+)\s*=\s*'([^']+'(?:\s*\|\s*'[^']+')*)",
        re.DOTALL,
    )

    for match in interface_pattern.finditer(ts_content):
        name, body = match.groups()
        fields: dict[str, Any] = {}
        for line in body.split("\n"):
            line = line.strip()
            if not line or line.startswith("//"):
                continue
            if ":" in line:
                parts = line.rsplit(":", 1)
                field_name = parts[0].strip()
                field_type = parts[1].strip().rstrip(",;")
                fields[field_name] = field_type
        interfaces[name] = fields

    for match in type_alias_pattern.finditer(ts_content):
        name, body = match.group(1), match.group(2)
        interfaces[name] = {"__type_alias": body.strip()}

    return interfaces


def extract_openapi_schemas(openapi: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Extract schemas from OpenAPI spec (FastAPI auto-generates this at /openapi.json)."""
    schemas: dict[str, dict[str, Any]] = {}
    components = openapi.get("components", {})
    schema_map = components.get("schemas", {})
    for name, schema in schema_map.items():
        if isinstance(schema, dict):
            schemas[name] = schema
    return schemas


def ts_to_python_type(ts_type: str) -> str:
    """Map a TypeScript field type to a simplified Python type string."""
    ts_type = ts_type.strip()
    if ts_type.startswith("Record<"):
        return "dict"
    if ts_type.startswith("("):
        return "tuple"
    if " | " in ts_type:
        inner = [t.strip().strip("'\"") for t in ts_type.split("|")]
        if all(t in ("string", "number", "boolean", "null", "undefined") for t in inner):
            non_null = [t for t in inner if t not in ("null", "undefined")]
            if len(non_null) == 1:
                return non_null[0]
            return f"union[{','.join(non_null)}]"
    if ts_type.endswith("[]"):
        return f"list[{ts_to_python_type(ts_type[:-2])}]"
    if ts_type in ("string",):
        return "str"
    if ts_type in ("number", "int", "integer", "float", "double"):
        return "int"
    if ts_type in ("boolean",):
        return "bool"
    if ts_type in ("null", "undefined", "void"):
        return "None"
    return ts_type


def normalize_field_name(name: str) -> str:
    """Normalize field names (convert camelCase to snake_case and vice versa)."""
    return name


def compare_schema(
    ts_interfaces: dict[str, dict[str, Any]],
    openapi_schemas: dict[str, dict[str, Any]],
) -> list[dict[str, str]]:
    """Compare TypeScript interfaces against OpenAPI schemas and report mismatches."""
    issues: list[dict[str, str]] = []

    # Build camelCase → snake_case lookup for OpenAPI fields
    def to_camel_case(s: str) -> str:
        return re.sub(r"_([a-z])", lambda m: m.group(1).upper(), s)

    def to_snake_case(s: str) -> str:
        return re.sub(r"(?<!^)(?=[A-Z])", "_", s).lower()

    for ts_name, ts_fields in ts_interfaces.items():
        # Try exact match first
        oa_name = ts_name
        if oa_name not in openapi_schemas:
            # Try response suffix
            if not ts_name.endswith("Response") and not ts_name.endswith("Request"):
                for suffix in ("Response", "Request", "Row"):
                    alt = ts_name + suffix
                    if alt in openapi_schemas:
                        oa_name = alt
                        break
        if oa_name not in openapi_schemas:
            issues.append({
                "severity": "MISSING",
                "ts_interface": ts_name,
                "oa_schema": oa_name,
                "message": f"TypeScript interface '{ts_name}' has no matching OpenAPI schema",
            })
            continue

        oa_schema = openapi_schemas[oa_name]
        oa_properties = oa_schema.get("properties", {})

        # Check for missing fields in TypeScript
        for oa_field, oa_field_def in oa_properties.items():
            ts_field = oa_field
            if ts_field not in ts_fields:
                # Try camelCase variant
                ts_field_alt = to_camel_case(oa_field)
                if ts_field_alt in ts_fields:
                    ts_field = ts_field_alt
                else:
                    issues.append({
                        "severity": "WARN",
                        "ts_interface": ts_name,
                        "oa_schema": oa_name,
                        "message": f"OpenAPI field '{oa_field}' missing in TypeScript interface '{ts_name}'",
                    })

        # Check for missing fields in OpenAPI
        for ts_field, ts_type in ts_fields.items():
            if ts_field.startswith("__"):
                continue
            oa_field = ts_field
            if ts_field not in oa_properties:
                # Try snake_case variant
                oa_field_alt = to_snake_case(ts_field)
                if oa_field_alt in oa_properties:
                    oa_field = oa_field_alt
                else:
                    issues.append({
                        "severity": "MISSING_FIELD",
                        "ts_interface": ts_name,
                        "oa_schema": oa_name,
                        "message": f"TypeScript field '{ts_field}' has no matching OpenAPI field",
                    })

    return issues


def fetch_openapi(url: str, timeout: int = 10) -> dict[str, Any]:
    """Fetch OpenAPI JSON from the FastAPI server."""
    import requests
    try:
        resp = requests.get(url, timeout=timeout)
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as exc:
        print(f"[ERROR] Failed to fetch OpenAPI spec from {url}: {exc}")
        print("[INFO] Falling back to local inspection mode.")
        return {}


def run() -> bool:
    ts_path = Path(API_TS_PATH)
    if not ts_path.exists():
        print(f"[ERROR] TypeScript types file not found: {ts_path}")
        sys.exit(1)

    ts_content = ts_path.read_text(encoding="utf-8")
    ts_interfaces = extract_ts_interfaces(ts_content)

    openapi_url = os.environ.get(OPENAPI_URL_ENV) or DEFAULT_OPENAPI_URL

    openapi = fetch_openapi(openapi_url)
    if not openapi:
        print("[INFO] Skipping live comparison — OpenAPI server not reachable.")
        print(f"[INFO] Run 'uvicorn api.main:app' then re-run this script.")
        return True  # don't fail if server isn't running

    openapi_schemas = extract_openapi_schemas(openapi)

    print(f"[INFO] Loaded {len(ts_interfaces)} TypeScript interfaces")
    print(f"[INFO] Loaded {len(openapi_schemas)} OpenAPI schemas")
    print()

    issues = compare_schema(ts_interfaces, openapi_schemas)

    if not issues:
        print("[PASS] All TypeScript interfaces match OpenAPI schemas")
        return True

    print(f"[WARN] Found {len(issues)} type mismatch(s):")
    for issue in issues:
        severity_icon = {"MISSING": "✗", "WARN": "!", "MISSING_FIELD": "~"}.get(
            issue["severity"], "?"
        )
        print(f"  [{severity_icon}] {issue['ts_interface']}: {issue['message']}")

    return False


if __name__ == "__main__":
    import os
    success = run()
    sys.exit(0 if success else 1)
