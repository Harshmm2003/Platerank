"""Shared Claude helper - the ONE place PlateRank calls the Claude API.

Every caller (Discovery answers, competitor suggestions, restaurant facts,
menu reading) goes through claude_call(), so model choice, web tools,
refusal fallbacks, cost tracking and error wording live in one file.

Tools are opt-in per call:
  web_search - Claude searches the web and cites sources ($10 per 1,000 searches + tokens)
  web_fetch  - Claude reads a specific URL it was given (tokens only)
Both must also be enabled for the organisation in the Claude Console.
Keys are read from the environment (.env) and never printed or logged.
"""
import os
from dataclasses import dataclass, field

# USD per million tokens (input, output) - platform.claude.com/docs pricing, Oct 2026.
PRICES = {
    "claude-fable-5-1": (10.0, 50.0),
    "claude-opus-5-5": (4.0, 20.0),
    "claude-sonnet-5-5": (2.0, 10.0),
    "claude-haiku-5-5": (0.10, 0.50),
}
WEB_SEARCH_USD = 0.01  # per search
# Models that accept server-side refusal fallbacks (routed by refusal category).
FALLBACK_MODELS = {"claude-opus-5-5", "claude-opus-5", "claude-fable-5-1", "claude-sonnet-5-5"}


class QuotaError(Exception):
    """The platform refused because the key's quota / rate limit is used up (HTTP 429)."""


class ClaudeUnavailable(Exception):
    """A plain-English reason Claude could not be used (no key, bad key, no credit, tool disabled...)."""


def has_key() -> bool:
    return bool((os.getenv("ANTHROPIC_API_KEY") or "").strip())


def default_model() -> str:
    return os.getenv("CLAUDE_MODEL", "claude-opus-5-5")


def discovery_model() -> str:
    """Model that answers the customer questions. Separate so the bulk run can be cheaper."""
    return os.getenv("CLAUDE_DISCOVERY_MODEL") or default_model()


def web_search_tool(max_uses: int = 3, location: dict | None = None, allowed_domains: list[str] | None = None) -> dict:
    tool = {"type": "web_search_20250305", "name": "web_search", "max_uses": max_uses}
    if location:
        tool["user_location"] = {"type": "approximate", **{k: v for k, v in location.items() if v}}
    if allowed_domains:
        tool["allowed_domains"] = allowed_domains
    return tool


def web_fetch_tool(max_uses: int = 3, max_content_tokens: int = 20000) -> dict:
    return {"type": "web_fetch_20250910", "name": "web_fetch", "max_uses": max_uses,
            "max_content_tokens": max_content_tokens}


def location_for(profile: dict) -> dict:
    """Approximate user location for web search, from the profile (city/region/country)."""
    city = (profile.get("city") or "").strip()
    loc = {"city": city or None, "country": profile.get("country") or "US"}
    if profile.get("state"):
        from .places import US_STATES
        loc["region"] = US_STATES.get(profile["state"], profile["state"])
    if city.lower() in ("new york", "new york city", "nyc", "brooklyn", "manhattan", "queens", "the bronx", "staten island"):
        loc.update(region="New York", timezone="America/New_York")
    return loc


@dataclass
class ClaudeResult:
    text: str
    model: str
    sources: list = field(default_factory=list)   # [{"url", "title"}] cited or searched
    searches: int = 0
    fetches: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    refused: bool = False

    @property
    def cost_usd(self) -> float:
        pin, pout = PRICES.get(self.model, PRICES.get(default_model(), (4.0, 20.0)))
        return round(self.input_tokens / 1e6 * pin + self.output_tokens / 1e6 * pout
                     + self.searches * WEB_SEARCH_USD, 4)


def _plain_reason(e: Exception) -> str:
    """Turn an SDK error into something an owner can act on."""
    import anthropic
    msg = str(e)
    if isinstance(e, anthropic.AuthenticationError):
        return "The Claude key in .env was rejected. Copy it again from console.anthropic.com -> API keys."
    if isinstance(e, anthropic.PermissionDeniedError):
        return "This Claude key isn't allowed to do that (check the key's workspace in the Console)."
    if isinstance(e, anthropic.BadRequestError):
        low = msg.lower()
        if "credit" in low or "balance" in low:
            return "The Claude account is out of credit. Add funds in console.anthropic.com -> Billing."
        if "web_search" in low or "web_fetch" in low or "tool" in low:
            return ("Claude's web search / web fetch is switched off for this organisation. Turn it on in "
                    "console.anthropic.com -> Settings -> Capabilities (or Privacy controls).")
        return "Claude rejected the request: " + msg[:200]
    if isinstance(e, anthropic.APIConnectionError):
        return "Couldn't reach Claude - check the internet connection and try again."
    if isinstance(e, anthropic.InternalServerError):
        return "Claude is busy right now. Wait a minute and try again."
    return f"Claude call failed ({type(e).__name__})."


_client = None


def _get_client():
    global _client
    if _client is None:
        import anthropic
        _client = anthropic.Anthropic(max_retries=3)
    return _client


def claude_call(prompt, system: str | None = None, model: str | None = None, tools: list | None = None,
                max_tokens: int = 8000, effort: str | None = "medium", tool_choice: dict | None = None) -> ClaudeResult:
    """One Claude request. prompt = a string or a list of content blocks (e.g. a PDF + text).
    Raises QuotaError on rate limits and ClaudeUnavailable with a plain-English reason otherwise.
    Newer request options (effort, refusal fallbacks) go in extra_body / extra_headers so this works
    with older and newer versions of the `anthropic` Python package alike."""
    if not has_key():
        raise ClaudeUnavailable("No ANTHROPIC_API_KEY in .env - add it to use live Claude features.")
    import anthropic
    model = model or default_model()
    content = prompt if isinstance(prompt, list) else [{"type": "text", "text": prompt}]
    kwargs = dict(model=model, max_tokens=max_tokens, messages=[{"role": "user", "content": content}])
    if system:
        kwargs["system"] = system
    if tools:
        kwargs["tools"] = tools
    if tool_choice:
        kwargs["tool_choice"] = tool_choice
    extra_body, extra_headers = {}, {}
    if effort:
        extra_body["output_config"] = {"effort": effort}
    if model in FALLBACK_MODELS:
        extra_body["fallbacks"] = "default"
        extra_headers["anthropic-beta"] = "server-side-fallback-2026-07-01"
    try:
        msg = _get_client().messages.create(**kwargs, extra_body=extra_body or None,
                                            extra_headers=extra_headers or None)
    except anthropic.RateLimitError as e:
        raise QuotaError(str(e)) from e
    except anthropic.APIError as e:
        raise ClaudeUnavailable(_plain_reason(e)) from e

    text, sources, seen = [], [], set()

    def add_source(url, title):
        if url and url not in seen:
            seen.add(url)
            sources.append({"url": url, "title": title or url})

    for b in msg.content:
        if b.type == "text":
            text.append(b.text)
            for c in getattr(b, "citations", None) or []:
                add_source(getattr(c, "url", None), getattr(c, "title", None))
        elif b.type == "web_search_tool_result" and isinstance(getattr(b, "content", None), list):
            for r in b.content:
                add_source(getattr(r, "url", None), getattr(r, "title", None))
    u = msg.usage
    stu = getattr(u, "server_tool_use", None)
    return ClaudeResult(
        text="".join(text), model=msg.model, sources=sources,
        searches=int(getattr(stu, "web_search_requests", 0) or 0) if stu else 0,
        fetches=int(getattr(stu, "web_fetch_requests", 0) or 0) if stu else 0,
        input_tokens=(u.input_tokens or 0) + (getattr(u, "cache_read_input_tokens", 0) or 0)
                     + (getattr(u, "cache_creation_input_tokens", 0) or 0),
        output_tokens=u.output_tokens or 0,
        refused=msg.stop_reason == "refusal")


def json_from(text: str):
    """Pull the first JSON array/object out of a model reply (tolerates ``` fences)."""
    import json
    start = min([i for i in (text.find("["), text.find("{")) if i >= 0], default=-1)
    end = max(text.rfind("]"), text.rfind("}"))
    if start < 0 or end < start:
        raise ValueError("no JSON in the reply")
    return json.loads(text[start:end + 1])
