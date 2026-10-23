"""Two-agent review of post drafts (Data farming) before the owner sees them.

A "Promoter" argues for posting (and may propose ONE edited version); a "Skeptic" checks the draft against a
fixed rule list. Both get the SAME context packet, built by code: the draft + target, the profile facts and
ONLY verified evidence (E1, E2...). Max 2 rounds, 2-4 calls, through platerank/llm.py.

What the AI does NOT decide:
- Step 0 is code: the fact guard + plain checks. A hard failure -> "Don't post", no Claude call.
- The VERDICT is computed by code from the rule results; the SUMMARY is a code template.
- Cited IDs that aren't in the packet are dropped and listed as "rejected citation".
- Same inputs -> the cached review, word for word (data/live/<slug>/agent_reviews/<hash>.json).
The owner still makes the final call; nothing is ever posted automatically (rule 4).

Model notes (claude-api skill, Oct 2026): Sonnet 5.5 rejects forced tool_choice ("any"/"tool") and any
non-default temperature with a 400, so each agent gets ONE strict tool with tool_choice "auto" and is told to
call it; the reply is validated by code (retry once, then FAILED - never invented). No temperature is sent.
"""
import hashlib, json, re

from . import content_gen, evidence, llm

PROMPT_VERSION = "review-v1"
RULES = [
    ("R1", "hard", "The owner's identity is disclosed (it says it comes from the restaurant's owner)."),
    ("R2", "hard", "Every factual claim matches a profile fact or a verified evidence ID."),
    ("R3", "hard", "No fake customer voice and no fake reviews."),
    ("R4", "hard", "No incentive for reviews and no asking for Yelp reviews."),
    ("R5", "hard", "No unsupported superlatives (e.g. 'best in San Diego')."),
    ("R6", "soft", "The tone fits the subreddit - helpful, not an ad."),
    ("R7", "soft", "If the subreddit's rules are unverified, the owner must read them before posting."),
]
RULE_IDS = [r[0] for r in RULES]
HARD = {r[0] for r in RULES if r[1] == "hard"}
VERDICTS = {"hard": "Don't post", "soft": "Post after edits", "pass": "Ready for you to post", "failed": "Review failed - decide yourself"}

PROMOTER_TOOL = {
    "name": "promoter_reply", "strict": True,
    "description": "Your argument for posting this draft, the IDs you rely on, and at most one edited version.",
    "input_schema": {"type": "object", "additionalProperties": False, "required": ["argument", "citations", "edited_text", "concede"],
                     "properties": {"argument": {"type": "string", "description": "2-4 sentences."},
                                    "citations": {"type": "array", "items": {"type": "string"},
                                                  "description": "Evidence IDs (E1...), rule IDs (R1...) or profile fact keys (fact:hours...)."},
                                    "edited_text": {"type": "string", "description": "ONE improved full draft, or an empty string for no edit."},
                                    "concede": {"type": "boolean", "description": "True if the Skeptic is right and it should not be posted."}}}}
SKEPTIC_TOOL = {
    "name": "skeptic_checks", "strict": True,
    "description": "One result for EVERY rule R1-R7.",
    "input_schema": {"type": "object", "additionalProperties": False, "required": ["checks"],
                     "properties": {"checks": {"type": "array", "items": {
                         "type": "object", "additionalProperties": False, "required": ["rule", "result", "reason", "cite"],
                         "properties": {"rule": {"type": "string", "enum": RULE_IDS}, "result": {"type": "string", "enum": ["pass", "fail"]},
                                        "reason": {"type": "string", "description": "One sentence."},
                                        "cite": {"type": "string", "description": "An evidence ID, rule ID or fact key - or an empty string."}}}}}}}
SYSTEM_A = ("You are the Promoter in a two-agent review of a draft a restaurant OWNER might post. Argue for posting it, honestly. "
            "Use ONLY the context packet: every claim you make must cite an evidence ID (E1...) or a profile fact key (fact:...). "
            "You may propose ONE edited version that fixes problems; never add facts that aren't in the packet. If the Skeptic is "
            "right and it can't be fixed, concede. Reply ONLY by calling the promoter_reply tool.")
SYSTEM_B = ("You are the Skeptic in a two-agent review of a draft a restaurant OWNER might post. Check the text against every rule "
            "R1-R7 in the context packet and give pass or fail with a one-sentence reason and the ID you rely on. Be strict on "
            "R1-R5. Use ONLY the packet. Reply ONLY by calling the skeptic_checks tool.")


# ---------------------------------------------------------------- context packet (identical for both agents)
def context_packet(slug: str, profile: dict, draft: dict) -> dict:
    facts = content_gen.pack_facts(profile)
    hh = re.search(r"happy hour[:\s]+([^;,\n]+)", profile.get("hours") or "", re.I)
    if hh:
        facts["happy_hour"] = hh.group(1).strip()
    recs = sorted((r for r in evidence.load(slug) if r.get("status") == evidence.VERIFIED), key=lambda r: r["id"])[:30]
    ev = [{"id": f"E{i + 1}", "kind": r["kind"], "about": r.get("subject", ""), "text": r["text"][:300], "source": r.get("source_url", "")}
          for i, r in enumerate(recs)]
    return {"draft": {"title": draft.get("title") or "", "text": draft["text"], "type": draft.get("type", "post")},
            "target": draft["target"], "target_rules_verified": bool(draft.get("rules_verified")),
            "facts": {f"fact:{k}": v for k, v in sorted(facts.items())}, "evidence": ev,
            "rules": [{"id": i, "level": lvl, "rule": t} for i, lvl, t in RULES]}


def cache_key(packet: dict, model: str) -> str:
    return hashlib.sha256(json.dumps({"packet": packet, "v": PROMPT_VERSION, "model": model}, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


# ---------------------------------------------------------------- step 0: code checks (no AI)
INCENTIVE_RE = re.compile(r"\byelp\b|leave (us )?a review|review us|for (a|your) review|discount .*review|free .*(review|post)", re.I)
SUPERLATIVE_RE = re.compile(r"\b(the )?best\b|#1\b|number one|award[- ]winning|world[- ]famous|unbeatable|greatest", re.I)
CUSTOMER_RE = re.compile(r"\b(i|we) (ate|tried|visited|went to|had dinner at)\b|\bas a (customer|regular|local diner)\b|\bmy (wife|husband|friends?) and i\b", re.I)


def code_checks(text: str, packet: dict, name: str) -> dict:
    """R1-R5 that plain code can decide, plus R7 from whether the rules were verified. {rule: (result, reason)}."""
    facts = {"name": name, "other_names": packet["facts"].get("fact:other_names", []), **{k.split(":", 1)[1]: v for k, v in packet["facts"].items()}}
    facts["evidence"] = [e["text"] for e in packet["evidence"]]
    _, flags = content_gen.guard_facts(text, facts)
    out = {"R1": ("pass", "Says it comes from the owner.") if re.search(rf"\bowner of {re.escape(name)}\b", text, re.I)
           else ("fail", "It doesn't say it comes from the restaurant's owner."),
           "R2": ("fail", "Not in your facts: " + ", ".join(flags)) if flags else ("pass", "Every checkable claim matches a profile fact."),
           "R3": ("fail", "It reads like a customer, not the owner.") if CUSTOMER_RE.search(text) else ("pass", "Written as the owner."),
           "R4": ("fail", "It asks for reviews or offers something for them.") if INCENTIVE_RE.search(text) else ("pass", "No review requests or incentives."),
           "R5": ("fail", f"Unsupported superlative: “{SUPERLATIVE_RE.search(text).group(0)}”.") if SUPERLATIVE_RE.search(text) else ("pass", "No superlatives.")}
    out["R7"] = (("pass", "The subreddit's rules were verified.") if packet["target_rules_verified"]
                 else ("fail", "We couldn't check this subreddit's rules - read them before posting."))
    return out


# ---------------------------------------------------------------- calling one agent (validated; retry once; never invented)
def _valid_promoter(x) -> bool:
    return isinstance(x, dict) and isinstance(x.get("argument"), str) and isinstance(x.get("citations"), list) \
        and all(isinstance(c, str) for c in x["citations"]) and isinstance(x.get("edited_text"), str) and isinstance(x.get("concede"), bool)


def _valid_skeptic(x) -> bool:
    if not (isinstance(x, dict) and isinstance(x.get("checks"), list)):
        return False
    seen = [c.get("rule") for c in x["checks"] if isinstance(c, dict)]
    return sorted(seen) == RULE_IDS and all(c.get("result") in ("pass", "fail") and isinstance(c.get("reason"), str)
                                           and isinstance(c.get("cite"), str) for c in x["checks"])


def _call(agent: str, message: dict, model: str) -> tuple[dict | None, float, int]:
    tool, system, valid = (PROMOTER_TOOL, SYSTEM_A, _valid_promoter) if agent == "A" else (SKEPTIC_TOOL, SYSTEM_B, _valid_skeptic)
    cost, calls = 0.0, 0
    for _ in range(2):  # one retry, then FAILED
        r = llm.claude_call(json.dumps(message, ensure_ascii=False, sort_keys=True), system=system, model=model, tools=[tool],
                            tool_choice={"type": "auto"}, max_tokens=3000, effort="low")
        cost, calls = cost + r.cost_usd, calls + 1
        got = next((t["input"] for t in r.tool_inputs if t["name"] == tool["name"]), None)
        if valid(got):
            return got, cost, calls
    return None, cost, calls


def _clean_citations(ids: list[str], packet: dict, who: str, rnd: int, rejected: list) -> list[str]:
    allowed = {e["id"] for e in packet["evidence"]} | set(RULE_IDS) | set(packet["facts"])
    kept = []
    for c in ids:
        c = c.strip()
        if not c:
            continue
        if c in allowed:
            kept.append(c)
        else:
            rejected.append({"agent": who, "round": rnd, "id": c})
    return kept


# ---------------------------------------------------------------- the review
def review(slug: str, profile: dict, draft: dict, fresh: bool = False, model: str | None = None) -> dict:
    model = model or llm.discovery_model()
    packet = context_packet(slug, profile, draft)
    key = cache_key(packet, model)
    path = evidence.ledger_path(slug).parent / "agent_reviews" / f"{key}.json"
    if path.exists() and not fresh:
        return {**json.loads(path.read_text(encoding="utf-8")), "cached": True, "cost": 0.0}
    name = profile["name"]
    transcript, rejected, cost, calls = [], [], 0.0, 0
    text = draft["text"]

    # step 0: code only
    code = code_checks(text, packet, name)
    hard_code = [r for r in HARD if code[r][0] == "fail"]
    if hard_code:
        checklist = [{"rule": r, "level": lvl, "result": code[r][0] if r in code else "not checked", "reason": code[r][1] if r in code else
                      "Not checked - a hard rule already failed.", "cite": r, "by": "code"} for r, lvl, _ in RULES]
        return _finish(path, draft, checklist, transcript, None, rejected, cost, calls, status="ok", stopped_by_code=True)

    suggested, checks, status = None, None, "ok"
    a_msg = {"packet": packet, "round": 1, "task": "Argue for posting this draft; propose at most one edit."}
    for rnd in (1, 2):
        a, c1, n1 = _call("A", a_msg, model)
        cost, calls = cost + c1, calls + n1
        if a is None:
            status = "failed"
            transcript.append({"agent": "Promoter", "round": rnd, "text": "No valid reply (tried twice) - marked FAILED.", "citations": []})
            break
        cites = _clean_citations(a["citations"], packet, "Promoter", rnd, rejected)
        edit = a["edited_text"].strip()
        if edit and edit != text:
            ec = code_checks(edit, packet, name)
            if any(ec[r][0] == "fail" for r in HARD):
                transcript.append({"agent": "Promoter", "round": rnd, "text": a["argument"], "citations": cites,
                                   "note": "Its edit was dropped - it failed the fact check: " + "; ".join(ec[r][1] for r in HARD if ec[r][0] == "fail")})
            else:
                text, suggested = edit, edit
                transcript.append({"agent": "Promoter", "round": rnd, "text": a["argument"], "citations": cites, "note": "Proposed an edited version."})
        else:
            transcript.append({"agent": "Promoter", "round": rnd, "text": a["argument"] + (" (concedes)" if a["concede"] else ""), "citations": cites})
        b, c2, n2 = _call("B", {"packet": {**packet, "draft": {**packet["draft"], "text": text}}, "round": rnd,
                                "promoter_argument": a["argument"], "checking": "the suggested edit" if suggested else "the original draft"}, model)
        cost, calls = cost + c2, calls + n2
        if b is None:
            status = "failed"
            transcript.append({"agent": "Skeptic", "round": rnd, "text": "No valid reply (tried twice) - marked FAILED.", "citations": []})
            break
        checks = sorted(b["checks"], key=lambda c: RULE_IDS.index(c["rule"]))
        for ch in checks:
            ch["cite"] = (_clean_citations([ch["cite"]], packet, "Skeptic", rnd, rejected) or [""])[0]
        fails = [ch for ch in checks if ch["result"] == "fail"]
        transcript.append({"agent": "Skeptic", "round": rnd, "citations": [ch["cite"] for ch in checks if ch["cite"]],
                           "text": ("Fails " + "; ".join(f"{ch['rule']}: {ch['reason']}" for ch in fails)) if fails else "All rules pass."})
        if not fails or rnd == 2:
            break  # stop early when everything passes; max 2 rounds
        a_msg = {"packet": {**packet, "draft": {**packet["draft"], "text": text}}, "round": 2,
                 "skeptic_checks": checks, "task": "Fix the failed rules with ONE edited version, or concede."}

    if status == "failed" or checks is None:
        return _finish(path, draft, [], transcript, suggested, rejected, cost, calls, status="failed")
    # code has the last word on what it can check (fact guard, owner identity, unverified rules)
    final_code = code_checks(text, packet, name)
    checklist = []
    for (rid, lvl, _), ch in zip(RULES, checks):
        res, why, by = ch["result"], ch["reason"], "Skeptic"
        if rid in final_code and final_code[rid][0] == "fail":
            res, why, by = "fail", final_code[rid][1], "code"
        checklist.append({"rule": rid, "level": lvl, "result": res, "reason": why, "cite": ch["cite"] or rid, "by": by})
    return _finish(path, draft, checklist, transcript, suggested, rejected, cost, calls, status="ok")


def verdict_of(checklist: list[dict], status: str = "ok") -> str:
    """Computed by code - never by the agents."""
    if status == "failed":
        return VERDICTS["failed"]
    if any(c["result"] == "fail" and c["rule"] in HARD for c in checklist):
        return VERDICTS["hard"]
    if any(c["result"] == "fail" for c in checklist):
        return VERDICTS["soft"]
    return VERDICTS["pass"]


def summary_of(verdict: str, checklist: list[dict], suggested: str | None, rejected: list[dict], status: str, stopped_by_code: bool) -> str:
    """A code template filled from the structured fields - no free-written summary."""
    if status == "failed":
        return "Verdict: Review failed - decide yourself. An agent didn't give a valid answer twice, so nothing was invented."
    passed = [c["rule"] for c in checklist if c["result"] == "pass"]
    failed = [f"{c['rule']} ({c['reason']})" for c in checklist if c["result"] == "fail"]
    parts = [f"Verdict: {verdict}.", ("Stopped by the fact check before any AI review. " if stopped_by_code else "") +
             (f"Passed: {', '.join(passed)}." if passed else "No rules passed.")]
    if failed:
        parts.append("Failed: " + "; ".join(failed) + ".")
    parts.append("Suggested edit: yes - see below." if suggested else "Suggested edit: none.")
    if rejected:
        parts.append("Rejected citations (not in the packet): " + ", ".join(f"{r['id']} ({r['agent']} round {r['round']})" for r in rejected) + ".")
    return " ".join(parts)


def _finish(path, draft, checklist, transcript, suggested, rejected, cost, calls, status="ok", stopped_by_code=False) -> dict:
    verdict = verdict_of(checklist, status)
    out = {"draft_key": draft.get("key"), "target": draft["target"], "status": status, "transcript": transcript, "checklist": checklist,
           "verdict": verdict, "summary": summary_of(verdict, checklist, suggested, rejected, status, stopped_by_code),
           "suggested_edit": suggested, "rejected_citations": rejected, "calls": calls, "cost": round(cost, 4),
           "prompt_version": PROMPT_VERSION, "label": "Two AI agents reviewed this. You decide."}
    if status == "ok":  # a FAILED review isn't cached - the next try may work
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({**out, "cost": 0.0, "first_cost": out["cost"]}, indent=1, ensure_ascii=False), encoding="utf-8")
    return {**out, "cached": False}
