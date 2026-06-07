"""WebSocket listener: receives Signal group messages and routes them to the pipeline."""

import asyncio
import json
import logging
import os
import re
import sys
from urllib.parse import urlparse

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
            return "pdf", {"path": att["filename"], "caption": msg.get("message", "")}

    text = (msg.get("message") or "").strip()
    match = URL_RE.search(text)
    if match:
        url = match.group(0)
        surrounding = (text[: match.start()] + text[match.end() :]).strip()
        return "url", {"url": url, "submitter_note": surrounding or None}

    if len(text) >= TEXT_MIN_CHARS:
        return "text", {"text": text}

    return "ignore", {}


async def _handle(envelope: dict, tags_file: str, vault_path: str, remote: str) -> None:
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
            content = extract_pdf(payload["path"])
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


async def _listen(
    ws_url: str,
    account: str,
    group_id: str,
    tags_file: str,
    vault_path: str,
    remote: str,
) -> None:
    async with websockets.connect(ws_url) as ws:
        logger.info("Connected to %s", ws_url)

        # Subscribe to receive messages for our account
        subscribe_req = {
            "jsonrpc": "2.0",
            "method": "subscribeReceive",
            "params": {"account": account},
            "id": 1,
        }
        await ws.send(json.dumps(subscribe_req))

        async for raw in ws:
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue

            # Filter to group messages from our target group only
            envelope = (msg.get("params") or {}).get("envelope") or {}
            data_message = envelope.get("dataMessage") or {}
            if data_message.get("groupInfo", {}).get("groupId") != group_id:
                continue

            asyncio.create_task(
                _handle(envelope, tags_file, vault_path, remote)
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

    delay = RECONNECT_DELAY_INITIAL
    while True:
        try:
            await _listen(ws_url, account, group_id, tags_file, vault_path, remote)
            delay = RECONNECT_DELAY_INITIAL
        except Exception as exc:
            logger.error("Connection error: %s — reconnecting in %ds", exc, delay)
            await asyncio.sleep(delay)
            delay = min(delay * 2, RECONNECT_DELAY_MAX)


if __name__ == "__main__":
    asyncio.run(main())
