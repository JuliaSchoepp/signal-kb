# Design notes

## Goals

- **Low-friction capture.** Members share things the way they already do — in a Signal group. No separate app, no bookmarking workflow.
- **Self-hosted.** Runs on commodity hardware (Raspberry Pi). No dependency on hyperscalers for the core pipeline.
- **Open formats.** Output is plain markdown with YAML frontmatter. The vault is portable and readable without any specific tool.
- **Versioned.** Git history provides audit trail, rollback, and offsite backup (GitHub).
- **IP-respectful.** Source articles are summarized, not reproduced verbatim. The repo can safely be public.
- **Privacy-preserving.** Sender identity is never persisted. The vault contains no information that could fingerprint contributors.

## Non-goals (v1)

- Bidirectional query interface (asking the bot questions in Signal).
- Multi-vault / multi-group support. One Signal group → one vault.
- Full-text search / RAG. Markdown + GitHub search is sufficient initially.
- Local LLM inference. Out of scope on Pi-class hardware.
- A web UI. The vault is consumed via Git clients and markdown readers.
- **Deduplication.** No measures are in place to detect duplicate submissions. Curation is the responsibility of group participants.

## Prior art

This project sits in an established lineage but does not have a direct equivalent.

- **Karpathy's "LLM Wiki" pattern.** Knowledge synthesized at ingest time, not query time. Markdown as durable storage. We adopt this philosophy directly.
- **Karakeepbot** (Telegram → Karakeep). Closest messenger-ingestion analog, but stores into a structured bookmark DB rather than flat markdown.
- **markdown-kb** (jeff377). GitHub-backed markdown KB with LINE Bot ingestion, but adds Postgres + pgvector for RAG. Heavier than needed.
- **signal-cli ecosystem** (AsamK, bbernhard). The de-facto unofficial Signal interface. We build on `signal-cli-rest-api`.

The specific combination — Signal as input, flat markdown as output, summarize-on-ingest, self-hosted on a Pi — is not addressed by any existing project as of this writing.

## Privacy

Both repositories are public. This makes the privacy safeguards load-bearing — they are not defense-in-depth, they are the only line of defense.

What is **never** written to disk or committed:

- Sender phone number, name, or any Signal identifier.
- Message timestamps. Only the publication date of the source (if explicitly stated in the content) is stored.
- The bot's own phone number or group ID. These live in `.env`, which is gitignored.
- Full source text. Articles are summarized; at most one short quote (under 15 words) may appear.

Enforcement is in code, not convention. The exclusions are structural: the pipeline never reads sender metadata from the WebSocket event, so there is nothing to accidentally log or commit.

## Summarization design choices

**Tag enum in schema.** The Claude API structured output constrains the model to tags from the controlled vocabulary at the decoding level. It cannot emit an invalid tag — no post-processing validation needed. Adding a tag is a one-line PR to the vault's `tags.yaml`; the pipeline picks it up on the next ingest without a restart.

**`source_date` extracted by LLM, not by parsing.** Publication dates appear in highly variable formats across sources. The LLM handles this flexibly. The "do not guess" instruction in the system prompt prevents fabrication.

**Slug generated in Python, not by LLM.** Deterministic generation with `python-slugify` is more predictable than LLM output for filename-safe strings, especially with German characters.

**One short quote maximum.** The system prompt limits quotation to at most one attributed quote under 15 words. This is both a copyright safeguard and a quality forcing function — it prevents the model from lazily reproducing source text instead of synthesizing it.
