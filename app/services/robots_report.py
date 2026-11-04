"""What robots.txt says about AI agents: the evidence behind a partial report when robots.txt closes the site to our scanner.

robots.txt is a convention, not a barrier: it tells crawlers what the site owner wants. We read it per agent so the owner (or a
reader) sees which assistants may fetch the site and which may not, even when our own scanner is not allowed in.
"""
from __future__ import annotations

from typing import Any

from app.config import settings
from app.services.crawler import Robots

# Agents that fetch pages for a person's question (search / on-demand fetch): blocking them keeps the site out of AI answers.
USER_FACING = (
    ("ChatGPT-User", "ChatGPT (page opened for a user)"),
    ("OAI-SearchBot", "ChatGPT search index"),
    ("Claude-User", "Claude (page opened for a user)"),
    ("Claude-SearchBot", "Claude search index"),
    ("PerplexityBot", "Perplexity search index"),
    ("Perplexity-User", "Perplexity (page opened for a user)"),
    ("Meta-ExternalFetcher", "Meta AI (page opened for a user)"),
    ("Googlebot", "Google Search / Gemini grounding"),
    ("bingbot", "Bing / Copilot"),
    ("Applebot", "Apple search and Siri"),
)
# Crawlers that collect content to train or improve models.
TRAINING = (
    ("GPTBot", "OpenAI training crawler"),
    ("ClaudeBot", "Anthropic training crawler"),
    ("anthropic-ai", "Anthropic (legacy token)"),
    ("Claude-Web", "Anthropic (legacy token)"),
    ("Google-Extended", "Google AI training opt-out token"),
    ("Applebot-Extended", "Apple AI training opt-out token"),
    ("Meta-ExternalAgent", "Meta AI crawler"),
    ("CCBot", "Common Crawl"),
    ("Bytespider", "ByteDance crawler"),
    ("Amazonbot", "Amazon crawler"),
    ("cohere-ai", "Cohere crawler"),
)


def robots_report(robots: Robots, origin: str) -> dict[str, Any]:
    """Per-agent allow/block table for the homepage, plus a verdict that mirrors disc.robots_ai (fail / warn / pass)."""
    url = origin.rstrip("/") + "/"
    agents: list[dict[str, Any]] = []
    for kind, group in (("user_facing", USER_FACING), ("training", TRAINING)):
        for token, label in group:
            agents.append({"agent": token, "label": label, "kind": kind, "allowed": robots.allowed(url, user_agent=token)})
    ours = settings.bot_user_agent.split("/")[0]
    blocked_user = [a["agent"] for a in agents if a["kind"] == "user_facing" and not a["allowed"]]
    blocked_training = [a["agent"] for a in agents if a["kind"] == "training" and not a["allowed"]]
    if blocked_user:
        status, summary = "fail", f"robots.txt blocks AI agents that fetch pages for users: {', '.join(blocked_user)}."
    elif blocked_training:
        status, summary = (
            "warn",
            f"Only training crawlers are blocked ({', '.join(blocked_training)}); user-facing agents are allowed.",
        )
    else:
        status, summary = "pass", "No AI agent is disallowed on the homepage."
    return {
        "origin": origin,
        "robots_chars": len(robots.text),
        "agents": agents,
        "scanner": {"agent": ours, "allowed": robots.allowed(url, user_agent=ours)},
        # an agent nobody named: what the catch-all group (*) decides for it
        "unlisted_agents_allowed": robots.allowed(url, user_agent="SomeUnlistedAgent"),
        "verdict": {
            "status": status,
            "summary": summary,
            "blocked_user_facing": blocked_user,
            "blocked_training": blocked_training,
        },
    }
