"""Shared fix draft shape. Every generator returns FixDraft; storage/API treat them uniformly."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


def snippet(node: dict[str, Any]) -> str:
    body = json.dumps(node, ensure_ascii=False, indent=2).replace("</", "<\\/")
    return f'<script type="application/ld+json">\n{body}\n</script>'


@dataclass
class FixDraft:
    check_id: str
    type: str  # jsonld | llms_txt | robots_txt
    title: str
    target_url: str
    placement: str = ""
    jsonld: dict[str, Any] | None = None
    content: str = ""  # file body (JSON pretty-printed for jsonld)
    filename: str = ""  # fixed name for file fixes (llms.txt, robots.txt)
    content_type: str = "text/plain"
    assumptions: list[str] = field(default_factory=list)
    todo: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    est_gain: float = 0.0

    def __post_init__(self) -> None:
        if self.jsonld is not None and not self.content:
            self.content = json.dumps(self.jsonld, ensure_ascii=False, indent=2)
            self.content_type = "application/ld+json"

    def payload(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "content": self.content, "filename": self.filename, "content_type": self.content_type,
            "placement": self.placement, "assumptions": self.assumptions, "todo": self.todo, "errors": self.errors,
        }
        if self.jsonld is not None:
            out.update(jsonld=self.jsonld, snippet=snippet(self.jsonld))
        return out
