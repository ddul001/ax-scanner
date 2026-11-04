"""Meta Model API (Muse Spark) client: OpenAI-compatible chat completions, structured output."""
from __future__ import annotations

import asyncio
import json
import logging
import re
from pathlib import Path
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from app.config import settings
from app.domain.models import HeuristicResult, LlmClassification, Signals

ModelT = TypeVar("ModelT", bound=BaseModel)

log = logging.getLogger(__name__)
PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "classify.md"
_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.I)


class LlmError(Exception):
    """Anything that keeps us from getting a usable model answer (transport, HTTP, invalid JSON)."""


def parse_model(content: str, model_cls: type[ModelT]) -> ModelT:
    """Parse the model's JSON even when it wraps it in code fences or adds prose before/after it."""
    text = _FENCE.sub("", content.strip())
    try:
        return model_cls.model_validate_json(text)
    except (ValidationError, ValueError) as first:
        decoder = json.JSONDecoder()
        for match in re.finditer(r"\{", text):
            try:
                obj, _ = decoder.raw_decode(text, match.start())
                return model_cls.model_validate(obj)
            except (ValueError, ValidationError):
                continue
        raise first


def build_payload(signals: Signals, heur: HeuristicResult) -> dict[str, Any]:
    """Compressed page description for the model (never raw HTML)."""
    text_fields = {
        "evidence", "text_excerpt", "nav_items", "title", "description", "headings",
        "cta_texts", "footer_text", "sitemap_samples", "jsonld_summary",
    }
    dumped = signals.model_dump(exclude=text_fields)
    return {
        "title": signals.title,
        "description": signals.description,
        "language": signals.language,
        "navigation": signals.nav_items,
        "headings": signals.headings,
        "main_buttons_and_calls_to_action": signals.cta_texts,
        "footer_text": signals.footer_text,
        "schema_org_summary": signals.jsonld_summary,
        "sample_urls_from_sitemap": signals.sitemap_samples,
        "text_excerpt": signals.text_excerpt,
        "signals": dumped,
        "heuristic": {"scores": heur.scores, "top": heur.top},
    }


def _strictify(node: Any) -> Any:
    """Strict structured-output rules: every object closed and with all its properties required."""
    if isinstance(node, dict):
        node.pop("default", None)
        if "properties" in node:
            node["additionalProperties"] = False
            node["required"] = list(node["properties"])
        for value in node.values():
            _strictify(value)
    elif isinstance(node, list):
        for value in node:
            _strictify(value)
    return node


def response_schema() -> dict[str, Any]:
    """JSON schema sent to the API (strict). `facts` is optional in Python so older cached answers still load."""
    schema = LlmClassification.model_json_schema()
    schema["properties"]["facts"] = {"$ref": "#/$defs/LlmFacts"}
    schema["properties"].pop("model_type", None)
    return _strictify(schema)


class MetaLlm:
    """Thin client for the Meta Model API; every call retries once on transient failures."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        timeout: float | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        reasoning_effort: str | None = None,
    ) -> None:
        self.api_key = settings.meta_api_key if api_key is None else api_key
        self.base_url = (base_url or settings.meta_api_base).rstrip("/")
        self.model = model or settings.meta_model
        self.reasoning_effort = settings.meta_reasoning_effort if reasoning_effort is None else reasoning_effort
        self._client = httpx.AsyncClient(timeout=timeout or settings.llm_timeout_s, transport=transport)
        self._system = PROMPT_PATH.read_text(encoding="utf-8")

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _send(self, body: dict[str, Any]) -> httpx.Response:
        """POST once more when Muse timed out or answered 429/5xx: those are transient, a different answer is a verdict."""
        url = f"{self.base_url}/chat/completions"
        headers = {"Authorization": f"Bearer {self.api_key}"}
        for attempt in range(2):
            try:
                resp = await self._client.post(url, json=body, headers=headers)
            except httpx.HTTPError as e:
                if attempt == 0:
                    await asyncio.sleep(settings.llm_retry_delay_s)
                    continue
                raise LlmError(f"request failed: {type(e).__name__}") from e
            if resp.status_code in (429, 500, 502, 503, 504) and attempt == 0:
                await asyncio.sleep(settings.llm_retry_delay_s)
                continue
            return resp
        raise LlmError("request failed")  # unreachable

    async def _chat(self, user: str, *, structured: bool) -> str:
        body: dict[str, Any] = {
            "model": self.model,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": self._system},
                {"role": "user", "content": user},
            ],
        }
        if self.reasoning_effort:
            body["reasoning_effort"] = self.reasoning_effort
        if structured:
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "site_classification",
                    "strict": True,
                    "schema": response_schema(),
                },
            }
        resp = await self._send(body)
        if resp.status_code == 400 and structured:
            return await self._chat(user, structured=False)  # API without json_schema support
        if resp.status_code != 200:
            log.warning("Muse API answered %s %s: %s", resp.status_code, resp.request.url, resp.text[:300].replace("\n", " "))
            raise LlmError(f"HTTP {resp.status_code}")
        try:
            return resp.json()["choices"][0]["message"]["content"]
        except (KeyError, IndexError, ValueError) as e:
            raise LlmError("unexpected response shape") from e

    async def classify(self, signals: Signals, heur: HeuristicResult) -> LlmClassification:
        if not self.configured:
            raise LlmError("META_API_KEY not set")
        user = json.dumps(build_payload(signals, heur), ensure_ascii=False)
        last: Exception | None = None
        for _ in range(2):  # one retry on invalid JSON
            content = await self._chat(user, structured=True)
            try:
                return parse_model(content, LlmClassification)
            except (ValidationError, ValueError) as e:
                last = e
                log.warning("invalid classifier JSON from LLM: %s", e)
        raise LlmError(f"invalid JSON after retry: {last}")

    async def structured(
        self,
        system: str,
        user: str,
        model_cls: type[ModelT],
        *,
        name: str = "answer",
        effort: str | None = None,
        usage: dict[str, int] | None = None,
    ) -> ModelT:
        """Generic strict-JSON call (used by the Agent Journey). Falls back to prompt-only JSON if the API says 400.

        `usage`, when given, is filled with the tokens the API reported (`reasoning_tokens`, `completion_tokens`), summed over
        the retry: the API exposes how much the model reasoned, not the reasoning text."""
        if not self.configured:
            raise LlmError("META_API_KEY not set")
        schema = _strictify(model_cls.model_json_schema())
        last: Exception | None = None
        for _ in range(2):
            body: dict[str, Any] = {
                "model": self.model,
                "temperature": 0,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {"name": name, "strict": True, "schema": schema},
                },
            }
            reasoning = self.reasoning_effort if effort is None else effort
            if reasoning:
                body["reasoning_effort"] = reasoning
            content = await self._post(body, usage)
            try:
                return parse_model(content, model_cls)
            except (ValidationError, ValueError) as e:
                last = e
                log.warning("invalid %s JSON from LLM: %s", name, e)
        raise LlmError(f"invalid JSON after retry: {last}")

    async def _post(self, body: dict[str, Any], usage: dict[str, int] | None = None) -> str:
        resp = await self._send(body)
        if resp.status_code == 400 and "response_format" in body:
            body = {k: v for k, v in body.items() if k != "response_format"}
            resp = await self._send(body)
        if resp.status_code != 200:
            log.warning("Muse API answered %s %s: %s", resp.status_code, resp.request.url, resp.text[:300].replace("\n", " "))
            raise LlmError(f"HTTP {resp.status_code}")
        try:
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, ValueError) as e:
            raise LlmError("unexpected response shape") from e
        if usage is not None:
            reported = data.get("usage") or {}
            reasoning = (reported.get("completion_tokens_details") or {}).get("reasoning_tokens")
            for key, value in (("reasoning_tokens", reasoning), ("completion_tokens", reported.get("completion_tokens"))):
                if isinstance(value, int):
                    usage[key] = usage.get(key, 0) + value
        return content
