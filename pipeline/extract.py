"""Content extraction for URLs, PDFs, and plain text."""

import logging
import os
import re
import tempfile
import urllib.request
from datetime import date

logger = logging.getLogger(__name__)

import fitz
import trafilatura

MAX_CHARS = 40_000
MAX_PDF_BYTES = 20 * 1024 * 1024  # 20 MB
MAX_HTML_BYTES = 10 * 1024 * 1024  # 10 MB

_USER_AGENT = "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)"

_URL_FULL_DATE_RE = re.compile(r"/(\d{4})/(\d{2})/(\d{2})/")
_URL_YEAR_MONTH_RE = re.compile(r"/(\d{4})/(\d{2})/")


class ExtractionError(Exception):
    pass


def _date_from_url_path(url: str) -> date | None:
    """Extract a date from URL path segments (full date or year+month only)."""
    m = _URL_FULL_DATE_RE.search(url)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            pass
    m = _URL_YEAR_MONTH_RE.search(url)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), 1)
        except ValueError:
            pass
    return None


def _extract_date(downloaded: str, url: str) -> date | None:
    """Try trafilatura page metadata first, fall back to URL path patterns."""
    try:
        from lxml import html as lxml_html
        from trafilatura.metadata import extract_metadata
        tree = lxml_html.fromstring(downloaded)
        meta = extract_metadata(tree, default_url=url)
        if meta and meta.date:
            return date.fromisoformat(meta.date[:10])
    except Exception:
        pass
    return _date_from_url_path(url)


def _extract_pdf_from_url(url: str) -> str:
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            tmp_path = f.name
        with urllib.request.urlopen(url, timeout=30) as response:
            data = response.read(MAX_PDF_BYTES + 1)
        if len(data) > MAX_PDF_BYTES:
            raise ExtractionError(
                f"PDF at {url} exceeds size limit ({MAX_PDF_BYTES // 1024 // 1024} MB)"
            )
        with open(tmp_path, "wb") as f:
            f.write(data)
        return extract_pdf(tmp_path)
    except ExtractionError:
        raise
    except Exception as exc:
        raise ExtractionError(f"Failed to download PDF from {url}: {exc}") from exc
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass


def extract_url(url: str) -> tuple[str, date | None]:
    if url.lower().split("?")[0].endswith(".pdf"):
        return _extract_pdf_from_url(url), _date_from_url_path(url)

    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            raw = response.read(MAX_HTML_BYTES)
    except Exception as exc:
        raise ExtractionError(f"Failed to fetch URL: {url}: {exc}") from exc
    downloaded = raw.decode("utf-8", errors="replace")
    if not downloaded:
        raise ExtractionError(f"Failed to fetch URL: {url}")
    text = trafilatura.extract(
        downloaded,
        include_tables=False,
        no_fallback=False,
        output_format="txt",
    )
    if not text:
        raise ExtractionError(f"No extractable text at URL: {url}")
    return text[:MAX_CHARS], _extract_date(downloaded, url)


def extract_pdf(path: str) -> str:
    try:
        doc = fitz.open(path)
    except Exception as exc:
        raise ExtractionError(f"Cannot open PDF {path}: {exc}") from exc
    with doc:
        pages = [page.get_text() for page in doc]
    text = "\n".join(pages).strip()
    if not text:
        text = _ocr_pdf(path)
    if not text:
        raise ExtractionError(f"No extractable text in PDF: {path}")
    return text[:MAX_CHARS]


def _ocr_pdf(path: str) -> str:
    try:
        import pytesseract
        from PIL import Image

        doc = fitz.open(path)
        pages = []
        with doc:
            for page in doc:
                pix = page.get_pixmap(dpi=150)
                img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                pages.append(pytesseract.image_to_string(img, lang="deu+eng"))
        return "\n".join(pages).strip()
    except Exception as exc:
        logger.warning("OCR fallback failed: %s", exc)
        return ""


def extract_text(text: str) -> str:
    return text[:MAX_CHARS]
