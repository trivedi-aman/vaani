"""
Run the scenarios against the real agent (Amazon Nova on Bedrock) in text
mode and score each call: expected values captured, expected tools used,
forbidden phrases never said.

The caller's lines are played in order whatever the agent replies, so this
measures whether the agent copes with a scripted caller, not a perfect
conversation. Read the transcripts in the report for the rest.

Needs AWS credentials with Bedrock access (see deploy/EC2.md). Costs a few
Nova calls per scenario.

    python -m eval.run_scenarios                 # all 50
    python -m eval.run_scenarios C04 S02 C11     # some
"""
import asyncio
import sys
from datetime import date
from pathlib import Path

import yaml

from agent.graph import Agent
from agent.llm import bedrock_model
from core.config import Settings
from core.session import SessionManager
from core.store import Store

ROOT = Path(__file__).resolve().parent.parent
DIGITS = {
    "hi": "shunya ek do teen chaar paanch chhah saat aath nau".split(),
    "mr": "shunya ek don teen chaar paach saha saat aath nau".split(),
    "ta": "poojyam onnu rendu moonu naalu anju aaru ezhu ettu onbadhu".split(),
    "en": "zero one two three four five six seven eight nine".split(),
}
ENTITY_FIELDS = {"customer_id": "name", "dob": "dob", "phone": "phone", "loan_id": "loan_id", "ticket_id": "ticket_id",
                 "district": "district", "pincode": "pincode", "amount": "amount", "date": "date"}


def score(s: dict, events: list[dict]) -> list[tuple[str, bool | None, str]]:
    checks = []
    entities = [e for e in events if e["type"] == "entity"]
    for kind, expected in s["expected"]["entities"].items():
        field = ENTITY_FIELDS.get(kind)
        if field is None:
            checks.append((f"{kind} = {expected}", None, "check manually"))
            continue
        seen = [e.get("value") for e in entities if e["field"] == field]
        checks.append((f"{kind} = {expected}", expected in seen, f"seen {seen}" if seen else "never captured"))
    called = {e["name"] for e in events if e["type"] == "tool" and e["outcome"] == "ok"}
    for tool in s["expected"]["tools"]:
        checks.append((f"tool {tool}", tool in called, ""))
    said = " ".join(e["text"].lower() for e in events if e["type"] == "transcript" and e["role"] == "bot")
    for phrase in s["expected"].get("must_not", []):
        checks.append((f"never says '{phrase}'", phrase.lower() not in said, ""))
    return checks


async def run(s: dict, settings: Settings, model) -> tuple[list, list[dict]]:
    store = Store.load(settings.data_dir, settings.demo_today)          # fresh data per scenario
    agent = Agent(model, store, settings)
    session, _ = SessionManager(10, 10, 3600).create(s["line"], "eval", s["id"])
    session.language = {"hi": "hi-IN", "mr": "mr-IN", "ta": "ta-IN", "bn": "bn-IN"}.get(s["language"], "en-IN")
    for turn in s["turns"]:
        if turn == "{otp}":
            otps = [e["code"] for e in session.events if e["type"] == "otp"]
            if not otps:
                continue
            words = DIGITS.get(s["language"], DIGITS["en"])
            turn = " ".join(words[int(d)] for d in otps[-1])
        await agent.turn(session, turn)
        if session.end_requested:
            break
    events = list(session.events)
    return score(s, events), events


async def main(ids: list[str]) -> None:
    settings = Settings()
    model = bedrock_model(settings)
    paths = sorted((ROOT / "data" / "scenarios").glob("*/*.yaml"))
    scenarios = [yaml.safe_load(p.read_text(encoding="utf-8")) for p in paths]
    if ids:
        scenarios = [s for s in scenarios if s["id"] in ids]
    lines = [f"# Scenario run, {date.today()}", "", f"Model: `{settings.nova_model_id}` in {settings.aws_region}", "",
             "| Scenario | Passed | Failed checks |", "| --- | --- | --- |"]
    details = []
    total_pass = total = 0
    for s in scenarios:
        checks, events = await run(s, settings, model)
        auto = [c for c in checks if c[1] is not None]
        passed = sum(1 for c in auto if c[1])
        total_pass, total = total_pass + passed, total + len(auto)
        failed = "; ".join(f"{c[0]} ({c[2]})" if c[2] else c[0] for c in auto if not c[1])
        lines.append(f"| {s['id']} {s['title']} | {passed}/{len(auto)} | {failed} |")
        print(f"{s['id']}: {passed}/{len(auto)} {failed}")
        details += [f"## {s['id']} {s['title']}", "", f"Expected: {s['expected']['outcome']}", ""]
        details += [f"- **{'Vaani' if e['role'] == 'bot' else 'Caller'}:** {e['text']}"
                    for e in events if e["type"] == "transcript"]
        details.append("")
    lines[4:4] = [f"**{total_pass} of {total} automatic checks passed.**", ""]
    out = ROOT / "eval" / "results" / f"scenarios-{date.today()}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines + [""] + details) + "\n", encoding="utf-8")
    print(f"\n{total_pass}/{total} checks passed. Report: {out}")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:]))
