"""Write a note file to the vault and commit + push to GitHub."""

import logging
import os
from datetime import date, datetime
from pathlib import Path

import git
from slugify import slugify

from .summarize import NoteData

logger = logging.getLogger(__name__)

_SLUG_REPLACEMENTS = [("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")]


def _make_slug(title: str) -> str:
    return slugify(title, replacements=_SLUG_REPLACEMENTS, max_length=50)


def _filing_date(note: NoteData) -> date:
    return note.source_date if note.source_date is not None else datetime.now().date()


def _note_path(vault_path: Path, filing: date, slug: str) -> Path:
    folder = vault_path / "notes" / filing.strftime("%Y-%m")
    stem = f"{filing.isoformat()}_{slug}"
    candidate = folder / f"{stem}.md"
    if not candidate.exists():
        return candidate
    for n in range(2, 1000):
        candidate = folder / f"{stem}-{n}.md"
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"Too many collisions for slug {slug} on {filing}")


def _render_tags(tags: list[str]) -> str:
    return "[" + ", ".join(tags) + "]"


def _yaml_str(value: str) -> str:
    safe = value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ").replace("\r", "")
    return f'"{safe}"'


def _render(note: NoteData, filing: date, source_url: str | None) -> str:
    url_value = source_url or "n/a"
    lines = [
        "---",
        f"title: {_yaml_str(note.title)}",
        f"date: {filing.isoformat()}",
        f"source_url: {url_value}",
        f"source_type: {note.note_type}",
        f"tags: {_render_tags(note.tags)}",
        f"note_type: {note.note_type}",
        "ingested_via: signal",
        "---",
        "",
        "## Summary",
        "",
        note.summary,
        "",
        "## Key points",
        "",
        *[f"- {point}" for point in note.key_points if len(point.strip()) > 2],
    ]

    if note.submitter_note:
        lines += ["", "## Submitter note", "", note.submitter_note]

    if source_url:
        lines += ["", "---", "", f"*Original: <{source_url}>*"]

    lines.append("")
    return "\n".join(lines)


def commit_note(
    note: NoteData,
    vault_path: str,
    remote: str = "origin",
    source_url: str | None = None,
) -> Path:
    root = Path(vault_path)
    filing = _filing_date(note)
    slug = _make_slug(note.title)
    note_file = _note_path(root, filing, slug)

    note_file.parent.mkdir(parents=True, exist_ok=True)
    note_file.write_text(_render(note, filing, source_url), encoding="utf-8")

    repo = git.Repo(root)
    repo.index.add([str(note_file.relative_to(root))])
    commit_title = note.title.replace("\n", " ").replace("\r", "")
    repo.index.commit(f"add: {commit_title}")

    try:
        repo.remotes[remote].push()
    except Exception as exc:
        logger.warning("git push failed (will retry on next run): %s", exc)

    return note_file
