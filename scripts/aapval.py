"""Validate AAP v3.0 payloads against the protocol's JSON schemas (used by the fixture scorer)."""
from __future__ import annotations

import glob
import json
import os
from typing import Any

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

BASE = os.path.join(os.path.dirname(__file__), "..", "aap-v3.0-spec", "schemas")
if not os.path.isdir(BASE):
    raise SystemExit(
        "aap-v3.0-spec/ is not in the repository: "
        "clone github.com/auto-agent-protocol/auto-agent-protocol into it first"
    )

resources = []
for path in glob.glob(BASE + "/**/*.json", recursive=True):
    with open(path, encoding="utf-8") as f:
        schema = json.load(f)
    resources.append((schema["$id"], Resource.from_contents(schema)))
REGISTRY = Registry().with_resources(resources)


def validate(name: str, data: Any) -> list[str]:
    """Errors of `data` against `<name>.schema.json`, as `path: message` lines (empty when valid)."""
    with open(f"{BASE}/{name}.schema.json", encoding="utf-8") as f:
        schema = json.load(f)
    validator = Draft202012Validator(schema, registry=REGISTRY)
    return [
        f"{'/'.join(map(str, error.absolute_path))}: {error.message[:160]}"
        for error in validator.iter_errors(data)
    ]
