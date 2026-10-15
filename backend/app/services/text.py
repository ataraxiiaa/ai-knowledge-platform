from dataclasses import dataclass
from pathlib import Path
import re
import unicodedata

from pypdf import PdfReader

from app.core.config import settings


class IngestionError(ValueError):
    """A safe, user-facing ingestion failure."""


@dataclass(frozen=True)
class TextChunk:
    content: str
    page: int
    chunk_index: int
    start: int
    end: int


def clean_text(text: str) -> str:
    text = unicodedata.normalize("NFC", text).replace("\x00", "")
    return re.sub(r"\s+", " ", text).strip()


def extract_pages(path: Path) -> list[tuple[int, str]]:
    try:
        reader = PdfReader(path)
        if reader.is_encrypted:
            raise IngestionError("Encrypted PDFs are not supported. Upload an unlocked PDF.")
        if len(reader.pages) > settings.MAX_PDF_PAGES:
            raise IngestionError(f"PDF exceeds the {settings.MAX_PDF_PAGES}-page limit.")
        pages = []
        total = 0
        for number, page in enumerate(reader.pages, 1):
            text = clean_text(page.extract_text() or "")
            total += len(text)
            if total > settings.MAX_DOCUMENT_CHARS:
                raise IngestionError("PDF contains too much extracted text.")
            if text:
                pages.append((number, text))
        if not pages:
            raise IngestionError("No extractable text found. Scanned PDFs need OCR, which is not supported yet.")
        return pages
    except IngestionError:
        raise
    except Exception as exc:
        raise IngestionError("Could not read this PDF. Upload a valid, text-based PDF.") from exc


def chunk_pages(pages: list[tuple[int, str]], size: int, overlap: int, max_chunks: int | None = None) -> list[TextChunk]:
    """Fixed-size Unicode character windows; overlap never crosses page boundaries."""
    if size <= 0 or not 0 <= overlap < size:
        raise ValueError("Require size > 0 and 0 <= overlap < size")
    chunks = []
    for page, text in pages:
        for start in range(0, len(text), size - overlap):
            end = min(start + size, len(text))
            content = text[start:end]
            if content.strip():
                if max_chunks is not None and len(chunks) >= max_chunks:
                    raise IngestionError("PDF creates too many chunks. Use a smaller document or larger chunk size.")
                chunks.append(TextChunk(content, page, len(chunks), start, end))
            if end == len(text):
                break
    return chunks
