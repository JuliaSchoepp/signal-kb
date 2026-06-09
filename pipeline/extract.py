"""Content extraction for URLs, PDFs, and plain text."""

import os
import tempfile
import urllib.request

import fitz
import trafilatura

MAX_CHARS = 40_000


class ExtractionError(Exception):
    pass


def _extract_pdf_from_url(url: str) -> str:
    try:
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            tmp_path = f.name
        urllib.request.urlretrieve(url, tmp_path)
        return extract_pdf(tmp_path)
    except ExtractionError:
        raise
    except Exception as exc:
        raise ExtractionError(f"Failed to download PDF from {url}: {exc}") from exc
    finally:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass


def extract_url(url: str) -> str:
    if url.lower().split("?")[0].endswith(".pdf"):
        return _extract_pdf_from_url(url)

    downloaded = trafilatura.fetch_url(url)
    if downloaded is None:
        raise ExtractionError(f"Failed to fetch URL: {url}")
    text = trafilatura.extract(
        downloaded,
        include_tables=False,
        no_fallback=False,
        output_format="txt",
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
