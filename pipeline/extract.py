"""Content extraction for URLs, PDFs, and plain text."""

import fitz
import trafilatura

MAX_CHARS = 40_000


class ExtractionError(Exception):
    pass


def extract_url(url: str) -> str:
    downloaded = trafilatura.fetch_url(url)
    if downloaded is None:
        raise ExtractionError(f"Failed to fetch URL: {url}")
    text = trafilatura.extract(
        downloaded,
        include_tables=False,
        no_fallback=False,
        output_format="text",
    )
    if not text:
        raise ExtractionError(f"No extractable text at URL: {url}")
    return text[:MAX_CHARS]


def extract_pdf(path: str) -> str:
    try:
        doc = fitz.open(path)
    except Exception as exc:
        raise ExtractionError(f"Cannot open PDF {path}: {exc}") from exc
    pages = [page.get_text() for page in doc]
    text = "\n".join(pages).strip()
    if not text:
        raise ExtractionError(f"No extractable text in PDF: {path}")
    return text[:MAX_CHARS]


def extract_text(text: str) -> str:
    return text[:MAX_CHARS]
