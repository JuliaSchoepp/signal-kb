"""Claude API call with structured output, producing a NoteData result."""

import json
import os
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import anthropic
import yaml

MODEL = "claude-sonnet-4-6"

_PROMPTS_DIR = Path(__file__).parent / "prompts"
SYSTEM_PROMPT = (_PROMPTS_DIR / "system_prompt.txt").read_text()


@dataclass
class NoteData:
    title: str
    summary: str
    key_points: list[str]
    tags: list[str]
    note_type: str
    source_date: date | None
    submitter_note: str | None


def _load_tags(tags_file: str) -> list[str]:
    with open(tags_file) as f:
        data = yaml.safe_load(f) or {}
    tags = data.get("tags", [])
    if not tags:
        raise ValueError(f"tags.yaml at {tags_file} has no tags defined")
    return tags


def _build_schema(tags: list[str]) -> dict:
    return {
        "type": "object",
        "properties": {
            "title": {"type": "string", "maxLength": 120},
            "summary": {"type": "string"},
            "key_points": {
                "type": "array",
                "items": {"type": "string"},
            },
            "tags": {
                "type": "array",
                "items": {"type": "string", "enum": tags},
            },
            "note_type": {
                "type": "string",
                "enum": ["article", "paper", "opinion", "reference"],
            },
            "source_date": {"type": ["string", "null"], "format": "date"},
            "submitter_note": {"type": ["string", "null"]},
        },
        "required": [
            "title",
            "summary",
            "key_points",
            "tags",
            "note_type",
            "source_date",
            "submitter_note",
        ],
        "additionalProperties": False,
    }


def _build_user_prompt(
    source_type: str,
    source_url: str | None,
    content: str,
    submitter_note: str | None,
    date_hint: date | None = None,
) -> str:
    url_line = source_url or "n/a"
    note_section = submitter_note or "(none)"
    hint_line = f"\nMETADATA DATE: {date_hint.isoformat()}" if date_hint else ""
    return (
        f"SOURCE TYPE: {source_type}\n"
        f"SOURCE URL: {url_line}{hint_line}\n\n"
        f"SOURCE CONTENT\n---\n{content}\n---\n\n"
        f"SUBMITTER NOTE\n{note_section}"
    )


def summarize(
    source_type: str,
    content: str,
    tags_file: str,
    source_url: str | None = None,
    submitter_note: str | None = None,
    date_hint: date | None = None,
) -> NoteData:
    tags = _load_tags(tags_file)
    schema = _build_schema(tags)
    user_prompt = _build_user_prompt(source_type, source_url, content, submitter_note, date_hint)

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    response = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
        output_config={
            "format": {
                "type": "json_schema",
                "schema": schema,
            }
        },
    )

    if not response.content:
        raise RuntimeError("Anthropic API returned an empty response")
    raw = json.loads(response.content[0].text)

    source_date = None
    if raw["source_date"]:
        source_date = date.fromisoformat(raw["source_date"])

    return NoteData(
        title=raw["title"],
        summary=raw["summary"],
        key_points=raw["key_points"],
        tags=raw["tags"],
        note_type=raw["note_type"],
        source_date=source_date,
        submitter_note=raw["submitter_note"],
    )
