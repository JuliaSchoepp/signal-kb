# signal-kb

A self-hosted pipeline that turns a Signal group into a versioned, markdown-based knowledge base.

Members share links, PDFs, and short notes in a Signal group. The bot extracts and summarizes each one via the Claude API and commits a structured markdown file to a Git repository. No separate app, no bookmarking workflow.

## How it works

```
┌──────────────────────┐
│   Signal group       │
│   (members + bot)    │
└──────────┬───────────┘
           │ messages
           ▼
┌──────────────────────────────┐
│  signal-cli-rest-api         │   Docker container, JSON-RPC mode
│  (Pi, localhost:8080)        │   Exposes WebSocket
└──────────┬───────────────────┘
           │ message events
           ▼
┌──────────────────────────────┐
│  Ingestion bot (Python)      │
│                              │
│  1. classify message         │   URL / PDF / text / ignore
│  2. fetch + extract          │   trafilatura / pymupdf / passthrough
│  3. summarize via Claude API │   structured output: title, summary,
│  4. write .md file           │   key points, tags, source date
│  5. git commit + push        │
└──────────────────────────────┘
           │
           ▼
┌──────────────────────────────┐
│  GitHub (vault repo)         │   Markdown files, offsite backup
└──────────────────────────────┘
```

The bot never replies in the Signal group. Sender identity is never written to disk.

### Content extraction

| Input | Detected by | Tool |
|---|---|---|
| URL | regex match on message text | `trafilatura` |
| PDF | attachment MIME type `application/pdf` | `pymupdf` |
| Plain text | ≥ 50 characters after stripping | passthrough |
| Ignored | everything else | — |

If a message contains both text and a URL, the URL is extracted as the primary source and the surrounding text is passed as a submitter note.

### Output file format

Each ingested item becomes a markdown file with YAML frontmatter:

```markdown
---
title: "EU AI Act: implementation timeline"
date: 2026-06-06
source_url: https://example.com/article
source_type: article
tags: [eu-politik, ki-regulierung]
note_type: article
ingested_via: signal
---

## Summary

One paragraph capturing the core argument or finding.

## Key points

- First takeaway
- Second takeaway
- Third takeaway

## Submitter note

Any text the sender added alongside the link.

---

*Original: <https://example.com/article>*
```

Files are written to `notes/YYYY-MM/YYYY-MM-DD_slug.md`. Same-day slug collisions get `-2`, `-3` suffixes.

### Filing date

The filename prefix and `date` frontmatter field use the **publication date of the source** if the Claude API can extract an explicit one, otherwise the ingestion date. An article published in March 2024 but shared today is filed under `2024-03/`. Opinion notes and other dateless content use the ingestion date.

### Slug generation

Slugs are generated deterministically in Python from the title using `python-slugify` with German transliteration (ä→ae, ö→oe, ü→ue, ß→ss), not by the LLM. This keeps filenames predictable and reproducible.

## Repository layout

```
pipeline/
    bot.py               WebSocket listener and message router
    extract.py           URL / PDF / text extraction
    summarize.py         Claude API call with structured output
    vault.py             Markdown rendering and git operations
    prompts/
        system_prompt.txt    LLM system prompt (edit to adjust tone/rules)
tags.example.yaml        Template for the vault's tags.yaml
docker-compose.yml       signal-cli-rest-api service definition
pyproject.toml           Python dependencies
.env.example             Required environment variables
systemd/
    kb-bot.service       systemd unit for process supervision
docs/
    setup.md             Step-by-step setup and Signal registration guide
    design.md            Goals, prior art, and design rationale
```

## Two-repo design

This repo contains only generic pipeline code. The vault — the actual markdown files, and the `tags.yaml` controlled vocabulary — lives in a separate repository. Anyone can fork this pipeline and point it at their own Signal group and vault.

## Prerequisites

- Raspberry Pi 5 (or equivalent) running 64-bit Linux
- Docker + Docker Compose
- Python 3.11+ and [uv](https://docs.astral.sh/uv/)
- A dedicated phone number for the bot (JMP.chat VoIP, ~$3/month)
- Anthropic API key
- A GitHub repository for the vault, with a write-access deploy key

## Setup

See [docs/setup.md](docs/setup.md) for the full walkthrough, including Signal registration and deploy key configuration.

Quick summary:

```bash
# 1. Clone and install
git clone https://github.com/your-org/signal-kb
cd signal-kb
uv sync

# 2. Configure
cp .env.example .env
# fill in ANTHROPIC_API_KEY, SIGNAL_ACCOUNT, SIGNAL_GROUP_ID, VAULT_PATH

# 3. Start signal-cli-rest-api
docker compose up -d

# 4. Install the systemd service
sudo cp systemd/kb-bot.service /etc/systemd/system/
sudo systemctl enable --now kb-bot
```

## Configuration

All configuration is through environment variables. See `.env.example` for the full list.

| Variable | Description |
|---|---|
| `ANTHROPIC_API_KEY` | Claude API key |
| `SIGNAL_WS_URL` | WebSocket URL (default: `ws://localhost:8080/v1/ws`) |
| `SIGNAL_ACCOUNT` | Bot phone number in E.164 format |
| `SIGNAL_GROUP_ID` | Base64 group ID of the target Signal group |
| `VAULT_PATH` | Absolute path to the vault repo working copy |
| `VAULT_TAGS_FILE` | Path to `tags.yaml` (default: `{VAULT_PATH}/tags.yaml`) |
| `GITHUB_REMOTE` | Git remote name (default: `origin`) |

## Tag vocabulary

Tags are defined in `tags.yaml` in the vault repo. The pipeline reads this file on every API call — adding a tag is a one-line PR to the vault, no pipeline restart needed. The LLM is constrained to this vocabulary via the JSON schema; it cannot emit a tag that isn't listed.

Copy `tags.example.yaml` to your vault repo as `tags.yaml` and populate it with your domain's terms. Tags must be kebab-case; use whatever language suits your vault.

## Adjusting the prompts

The LLM system prompt lives in `pipeline/prompts/system_prompt.txt`. Edit it directly to change summarization tone, output language rules, or content quality instructions. The user prompt template is constructed in `pipeline/summarize.py`.

## Privacy

- Sender phone number, name, and Signal identifier are never written to disk or committed.
- Message timestamps are not recorded; only the publication date of the source (if explicitly stated) is stored.
- Bot phone number and group ID live in `.env`, which is gitignored.
- The vault can safely be public: source content is summarized, not reproduced.
