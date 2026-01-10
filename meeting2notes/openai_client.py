"""
OpenAI chat wrapper and higher-level meeting functions.

Contains:
- chat_completion: thin requests wrapper to OpenAI-style chat completions
- build_meeting_map: pass 1 (structure extraction)
- generate_meeting_title_from_map: title generation
- generate_meeting_notes: pass 2 notes generation
- cost helpers: estimate_cost_gbp, format_usage
"""

from __future__ import annotations

import json
import re
from typing import Tuple

import requests

from .config import OPENAI_BASE_URL, CHAT_MODEL, PRICING_GBP
from .timing import status


def chat_completion(
    api_key: str,
    messages: list[dict],
    temperature: float,
    model: str = CHAT_MODEL,
    return_usage: bool = False,
) -> Tuple[str, dict] | str:
    url = f"{OPENAI_BASE_URL}/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    r = requests.post(
        url,
        headers=headers,
        data=json.dumps({"model": model, "temperature": temperature, "messages": messages}),
        timeout=300,
    )

    if r.status_code != 200:
        raise RuntimeError(f"Chat completion failed ({r.status_code}): {r.text}")

    data = r.json()
    content = (data["choices"][0]["message"]["content"] or "").strip()
    usage = data.get("usage", {})
    return (content, usage) if return_usage else content


def build_meeting_map(api_key: str, transcript: str) -> tuple[dict, dict]:
    raw, usage = chat_completion(
        api_key,
        model=CHAT_MODEL,
        temperature=0.2,
        return_usage=True,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are an expert technical research assistant.\n"
                    "Extract a structured meeting map from a transcript.\n"
                    "Return ONLY valid JSON (parseable by json.loads). No markdown, no commentary.\n\n"
                    "Prioritise:\n"
                    "- Correct topic segmentation\n"
                    "- Capturing paper-writing structure/framing when present\n"
                    "- Capturing engineering/setup attempts + blockers when present\n"
                    "- Information-dense bullet fragments (no narration)\n"
                ),
            },
            {"role": "user", "content": f"""
Extract a JSON object with EXACTLY this schema:

{{
  "topics": [
    {{
      "name": "short topic label",
      "time_range_hint": "early/mid/late or empty string",
      "details": ["dense bullet fragments capturing substance and rationale"],
      "paper_structure": ["outline/sections/framing/contributions/eval plan/related work if relevant"],
      "tooling_setup": ["what was tried, environment assumptions, components, commands, blockers if relevant"],
      "decisions_explicit": ["only if explicitly decided"],
      "emerging_directions": ["tentative preferences/directions; NOT decisions"],
      "action_items": [
        {{
          "action": "action described",
          "owner": "name or TBC",
          "due": "date or TBC"
        }}
      ],
      "risks_blockers": ["explicit risks/blockers; prefix inferred ones with 'Potential:'"],
      "open_questions": ["questions raised or left unresolved"]
    }}
  ],
  "summary_bullets": ["8–12 bullets capturing overall outcomes and themes"],
  "decisions": ["explicit decisions only; empty list if none"],
  "action_items": [
    {{
      "action": "action described",
      "owner": "name or TBC",
      "due": "date or TBC"
    }}
  ],
  "emerging_directions": ["tentative directions across the whole meeting"],
  "keywords": ["important names: tools, frameworks, scenarios, paper sections, datasets, systems"]
}}

Rules:
- Do NOT invent facts.
- No narration ('we discussed', 'the team').
- Prefer concrete artefacts (paper sections, simulator names, scenarios, frameworks, components).
- If both paper-structure and tool/setup occur, they MUST appear as separate topics.
- Ensure each major topic has at least 6 bullets in 'details' (unless the transcript is genuinely short).

Transcript:
{transcript}
"""},
        ],
    )

    cleaned = re.sub(r"^```json\s*|\s*```$", "", raw.strip(), flags=re.DOTALL)
    m = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
    if not m:
        raise RuntimeError(f"Pass 1 did not return JSON:\n{raw}")
    return json.loads(m.group(0)), usage


def generate_meeting_title_from_map(api_key: str, meeting_map: dict) -> tuple[str, dict]:
    payload = {
        "summary_bullets": meeting_map.get("summary_bullets", []),
        "topics": [t.get("name", "") for t in meeting_map.get("topics", [])],
        "keywords": meeting_map.get("keywords", []),
    }

    title, usage = chat_completion(
        api_key,
        model=CHAT_MODEL,
        temperature=0.3,
        return_usage=True,
        messages=[
            {
                "role": "system",
                "content": (
                    "Generate a short, descriptive title (3–10 words) for technical/research meetings. "
                    "Be specific. Avoid dates and avoid the word 'meeting'. "
                    "Avoid generic titles like 'Project Update'."
                ),
            },
            {"role": "user", "content": "Generate a concise title from the structured summary below.\n\n"
                                        f"{json.dumps(payload, ensure_ascii=False)}"},
        ],
    )

    title = title.strip().strip('"')
    return (title.splitlines()[0].strip() or "Untitled"), usage


def generate_meeting_notes(
    api_key: str,
    transcript: str,
    meeting_map: dict,
    meeting_title: str,
    timestamp: str,
    *,
    pass2_model: str = CHAT_MODEL,
) -> tuple[str, dict]:
    notes_md, notes_usage = chat_completion(
        api_key,
        model=pass2_model,
        temperature=0.3,
        return_usage=True,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are an expert technical editor producing Notion-style meeting notes "
                    "for academic and research-oriented discussions.\n\n"
                    "Hard requirements:\n"
                    "- British English\n"
                    "- Bullet points only (no paragraphs)\n"
                    "- No narration ('we', 'the team', 'they discussed')\n"
                    "- Information-dense bullets: include rationale, constraints, and trade-offs\n"
                    "- Group content by topic using the topic names from meeting_map\n"
                    "- Do not invent facts, decisions, or action items\n"
                    "- If something is uncertain, label it as 'Unclear:' or 'Tentative:'\n"
                ),
            },
            {"role": "user", "content": f"""
Write detailed meeting notes using meeting_map as the authoritative structure.

Style:
- Concise bullet fragments (scan-friendly).
- Prefer specific technical nouns (tools, components, paper sections, scenarios) over generic phrasing.
- Depth targets: 8–12 bullets in Summary; 8–20 bullets per major topic in Key points.

Output Markdown using EXACTLY these headings and order:

---

# {meeting_title}

## Date and time
- {timestamp}

## Summary
- 8–12 dense bullets capturing the core themes/outcomes (no narration)

## Key points
- For each topic, use:
  - **Topic: <name>**
    - bullets (include paper_structure/tooling_setup detail when present)

## Decisions
- If none: "No formal decisions recorded."
- Otherwise: bullets of explicit decisions only.

## Action items
- Checklist only:
  - [ ] Action (Owner: ___, Due: ___)
- If none: "- [ ] None recorded (Owner: TBC, Due: TBC)"

## Risks / blockers
- Bullets (prefix inferred ones with "Potential:")

## Open questions
- Bullets, grouped by topic if useful

---

meeting_map:
{json.dumps(meeting_map, ensure_ascii=False)}

Transcript (for grounding only; do not quote large chunks):
{transcript}
"""},
        ],
    )
    return notes_md, notes_usage


def estimate_cost_gbp(model: str, usage: dict) -> float:
    pricing = PRICING_GBP.get(model)
    if not pricing or not usage:
        return 0.0
    in_tokens = usage.get("prompt_tokens", 0)
    out_tokens = usage.get("completion_tokens", 0)
    return (in_tokens / 1000) * pricing["input_per_1k"] + (out_tokens / 1000) * pricing["output_per_1k"]


def format_usage(label: str, model: str, usage: dict) -> tuple[str, float]:
    cost = estimate_cost_gbp(model, usage)
    line = f"{label:<25} tokens={usage.get('total_tokens', 0):>6}  cost=£{cost:.4f}"
    return line, cost
