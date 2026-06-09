"""WebSocket listener: receives Signal group messages and routes them to the pipeline."""

import asyncio
import json
import logging
import os
import re
import sys

import httpx
import websockets
from dotenv import load_dotenv

from .extract import ExtractionError, extract_pdf, extract_text, extract_url
from .summarize import summarize
from .vault import commit_note

load_dotenv()

logger = logging.getLogger(__name__)

URL_RE = re.compile(r"https?://[^\s]+")
TEXT_MIN_CHARS = 50
RECONNECT_DELAY_INITIAL = 2
RECONNECT_DELAY_MAX = 60


def _env(key: str) -> str:
    val = os.environ.get(key)
    if not val:
        raise RuntimeError(f"Required env var {key!r} is not set")
    return val


def _classify(envelope: dict) -> tuple[str, dict]:
    """Return (kind, payload) where kind is 'url' | 'pdf' | 'text' | 'ignore'."""
    msg = envelope.get("dataMessage") or {}
    attachments = msg.get("attachments", [])

    for att in attachments:
        if att.get("contentType") == "application/pdf":
            return "pdf", {"id": att["id"], "caption": msg.get("message", "")}

    text = (msg.get("message") or "").strip()
    match = URL_RE.search(text)
    if match:
        url = match.group(0)
        surrounding = (text[: match.start()] + text[match.end() :]).strip()
        return "url", {"url": url, "submitter_note": surrounding or None}

    if len(text) >= TEXT_MIN_CHARS:
        return "text", {"text": text}

    return "ignore", {}


async def _send_reaction(
    api_url: str,
    account: str,
    group_recipient: str,
    source_uuid: str,
    timestamp: int,
) -> None:
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{api_url}/v1/reactions/{account}",
            json={
                "recipient": group_recipient,
                "reaction": "✅",
                "target_author": source_uuid,
                "timestamp": timestamp,
            },
            timeout=10,
        )
        if resp.status_code not in (200, 201, 204):
            logger.warning("Reaction failed %s: %s", resp.status_code, resp.text[:200])


async def _handle(
    envelope: dict,
    tags_file: str,
    vault_path: str,
    remote: str,
    api_url: str,
    account: str,
    group_recipient: str,
    attachments_path: str,
) -> None:
    kind, payload = _classify(envelope)
    if kind == "ignore":
        return

    try:
        if kind == "url":
            content = extract_url(payload["url"])
            note = summarize(
                source_type="url",
                content=content,
                tags_file=tags_file,
                source_url=payload["url"],
                submitter_note=payload.get("submitter_note"),
            )
            path = commit_note(note, vault_path, remote, source_url=payload["url"])

        elif kind == "pdf":
            pdf_path = os.path.join(attachments_path, payload["id"])
            content = extract_pdf(pdf_path)
            note = summarize(
                source_type="pdf",
                content=content,
                tags_file=tags_file,
            )
            path = commit_note(note, vault_path, remote)

        elif kind == "text":
            content = extract_text(payload["text"])
            note = summarize(
                source_type="text",
                content=content,
                tags_file=tags_file,
            )
            path = commit_note(note, vault_path, remote)

    except ExtractionError as exc:
        logger.error("Extraction failed (%s): %s", kind, exc)
        return
    except Exception as exc:
        logger.exception("Unexpected error processing %s message: %s", kind, exc)
        return

    logger.info("Ingested → %s", path)

    source_uuid = envelope.get("sourceUuid")
    msg_timestamp = envelope.get("timestamp")
    if source_uuid and msg_timestamp:
        try:
            await _send_reaction(api_url, account, group_recipient, source_uuid, msg_timestamp)
        except Exception as exc:
            logger.warning("Could not send reaction: %s", exc)


async def _listen(
    ws_url: str,
    account: str,
    group_id: str,
    tags_file: str,
    vault_path: str,
    remote: str,
    api_url: str,
    group_recipient: str,
    attachments_path: str,
) -> None:
    async with websockets.connect(ws_url) as ws:
        logger.info("Connected to %s", ws_url)

        async for raw in ws:
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue

            # signal-cli-rest-api /v1/receive delivers {"envelope": {...}, "account": "..."}
            envelope = msg.get("envelope") or {}
            data_message = envelope.get("dataMessage") or {}
            if data_message.get("groupInfo", {}).get("groupId") != group_id:
                continue

            asyncio.create_task(
                _handle(envelope, tags_file, vault_path, remote, api_url, account, group_recipient, attachments_path)
            )


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        stream=sys.stdout,
    )

    ws_url = _env("SIGNAL_WS_URL")
    account = _env("SIGNAL_ACCOUNT")
    group_id = _env("SIGNAL_GROUP_ID")
    vault_path = _env("VAULT_PATH")
    tags_file = os.environ.get("VAULT_TAGS_FILE") or f"{vault_path}/tags.yaml"
    remote = os.environ.get("GITHUB_REMOTE", "origin")
    api_url = os.environ.get("SIGNAL_API_URL", "http://localhost:8080")
    attachments_path = _env("SIGNAL_ATTACHMENTS_PATH")

    # Look up the group's send-recipient ID (group.XXX= format) by internal_id
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{api_url}/v1/groups/{account}", timeout=10)
        resp.raise_for_status()
        groups = resp.json()
    group_recipient = next(
        (g["id"] for g in groups if g.get("internal_id") == group_id),
        None,
    )
    if not group_recipient:
        raise RuntimeError(f"Group with internal_id {group_id!r} not found via API")
    logger.info("Group recipient: %s", group_recipient)

    delay = RECONNECT_DELAY_INITIAL
    while True:
        try:
            await _listen(ws_url, account, group_id, tags_file, vault_path, remote, api_url, group_recipient, attachments_path)
            delay = RECONNECT_DELAY_INITIAL
        except Exception as exc:
            logger.error("Connection error: %s — reconnecting in %ds", exc, delay)
            await asyncio.sleep(delay)
            delay = min(delay * 2, RECONNECT_DELAY_MAX)


if __name__ == "__main__":
    asyncio.run(main())
