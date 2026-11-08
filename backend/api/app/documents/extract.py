"""Reading uploaded files: what they are, and the text in them (ADR 0004).

`identify` decides what a file is from its content, not its name, and refuses what we can't or
won't read. `extract` pulls out text in segments that record where each came from (a PDF page,
a Word section, a range of lines), with warnings for anything a reviewer must know: a page with
no readable text is flagged, never quietly treated as complete.

Supported so far: PDF with a text layer, Word (.docx) and plain text. PowerPoint, Excel and CSV
come next, then scanned pages and images (OCR, with Tesseract).
"""

import re
import zipfile
from dataclasses import dataclass, field
from io import BytesIO

from app.core.config import get_settings

CONTENT_TYPES = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "txt": "text/plain; charset=utf-8",
}
# Below this many characters a page is treated as having no readable text.
MIN_PAGE_CHARS = 15
# Word and text files have no pages: their text is cut into sections of about this size.
SECTION_CHARS = 3000

_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


class UnreadableFile(Exception):
    """A file we won't or can't read, with a message for the person who uploaded it."""


@dataclass
class Segment:
    kind: str  # "page", "section" or "lines"
    number: int
    text: str
    label: str | None = None
    method: str = "text"
    confidence: float | None = None
    flags: list[str] = field(default_factory=list)


@dataclass
class Extraction:
    segments: list[Segment]
    warnings: list[str]


def clean(text: str) -> str:
    """Normal line endings, no control characters, no trailing spaces, at most one blank line."""
    text = _CONTROL.sub("", text.replace("\r\n", "\n").replace("\r", "\n"))
    text = "\n".join(line.rstrip() for line in text.split("\n"))
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _pages(numbers: list[int]) -> str:
    return ("Page " if len(numbers) == 1 else "Pages ") + ", ".join(str(n) for n in numbers)


# --- What is it? ---------------------------------------------------------------------------------


def identify(filename: str, data: bytes) -> str:
    """The file's kind ("pdf", "docx" or "txt"), from its content. Raises UnreadableFile."""
    settings = get_settings()
    if not data:
        raise UnreadableFile("The file is empty.")
    if len(data) > settings.document_max_mb * 1024 * 1024:
        raise UnreadableFile(f"The file is larger than {settings.document_max_mb} MB.")
    if data.startswith(b"%PDF-"):
        return "pdf"
    if data.startswith(b"PK\x03\x04"):
        return _identify_office(data)
    if data.startswith((b"\xff\xd8\xff", b"\x89PNG\r\n\x1a\n")):
        raise UnreadableFile(
            "Photos and scanned images need their text read from the picture (OCR), which "
            "isn't available yet. Upload a PDF or Word file with the text in it for now."
        )
    if data.startswith((b"\xd0\xcf\x11\xe0", b"{\\rtf")):
        raise UnreadableFile(
            "Older Word (.doc) and rich-text files can't be read. Save it as .docx or PDF first."
        )
    name = filename.lower()
    if name.endswith((".txt", ".text", ".md")) and _looks_like_text(data):
        return "txt"
    raise UnreadableFile(
        "This kind of file isn't supported. Upload a PDF, a Word file (.docx) or a text file."
    )


def _identify_office(data: bytes) -> str:
    """A zip-based Office file. Checks the archive won't unpack into something huge."""
    settings = get_settings()
    try:
        archive = zipfile.ZipFile(BytesIO(data))
        names = archive.namelist()
        unpacked = sum(info.file_size for info in archive.infolist())
        types = archive.read("[Content_Types].xml").decode("utf-8", "replace")
    except (zipfile.BadZipFile, KeyError, OSError) as error:
        raise UnreadableFile("This file looks damaged, or isn't an Office document.") from error
    if len(names) > 5000 or unpacked > settings.document_max_unzipped_mb * 1024 * 1024:
        raise UnreadableFile("This file unpacks to more than we can safely read.")
    if "macroEnabled" in types or "vbaProject" in types:
        raise UnreadableFile(
            "Files with macros can't be uploaded. Save it as an ordinary .docx or PDF first."
        )
    if "wordprocessingml.document.main" in types:
        return "docx"
    if "presentationml" in types or "spreadsheetml" in types:
        raise UnreadableFile(
            "PowerPoint and Excel files aren't supported yet. Save it as PDF to upload it now."
        )
    raise UnreadableFile("This kind of Office file isn't supported.")


def _looks_like_text(data: bytes) -> bool:
    return b"\x00" not in data[:8192]


def decode_text(data: bytes) -> tuple[str, bool]:
    """The text, and whether it had to be read as Windows-1252 rather than UTF-8."""
    try:
        return data.decode("utf-8-sig"), False
    except UnicodeDecodeError:
        return data.decode("cp1252", errors="replace"), True


# --- Extracting the text -----------------------------------------------------------------------


def extract(kind: str, data: bytes) -> Extraction:
    if kind == "pdf":
        return _extract_pdf(data)
    if kind == "docx":
        return _extract_docx(data)
    if kind == "txt":
        return _extract_txt(data)
    raise UnreadableFile("This kind of file isn't supported.")


def _extract_pdf(data: bytes) -> Extraction:
    import pypdfium2 as pdfium

    settings = get_settings()
    try:
        pdf = pdfium.PdfDocument(data)
    except pdfium.PdfiumError as error:
        if "password" in str(error).lower():
            raise UnreadableFile(
                "This PDF is password-protected. Remove the password and upload it again."
            ) from error
        raise UnreadableFile("This PDF looks damaged and couldn't be opened.") from error
    try:
        count = len(pdf)
        if count == 0:
            raise UnreadableFile("This PDF has no pages.")
        if count > settings.document_max_pages:
            raise UnreadableFile(
                f"This PDF has {count} pages; the most we take is {settings.document_max_pages}. "
                "Split it into parts."
            )
        chapters = _pdf_chapters(pdf, count)
        segments = []
        for index in range(count):
            page = pdf[index]
            textpage = page.get_textpage()
            text = clean(textpage.get_text_range())
            textpage.close()
            page.close()
            segment = Segment(kind="page", number=index + 1, text=text, label=chapters[index])
            if len(text) < MIN_PAGE_CHARS:
                segment.flags.append("no_text")
            segments.append(segment)
    finally:
        pdf.close()

    warnings = []
    blank = [s.number for s in segments if "no_text" in s.flags]
    if len(blank) == len(segments):
        warnings.append(
            "No readable text was found: this PDF looks scanned. Reading scanned pages (OCR) "
            "isn't available yet, so approving it would add nothing."
        )
    elif blank:
        warnings.append(
            f"{_pages(blank)} have no readable text (they may be scanned pictures or diagrams). "
            "Anything on them won't be used."
            if len(blank) > 1
            else f"{_pages(blank)} has no readable text (it may be a scanned picture or a "
            "diagram). Anything on it won't be used."
        )
    return Extraction(segments=segments, warnings=warnings)


def _pdf_chapters(pdf, count: int) -> list[str | None]:
    """For each page, the title of the last bookmark at or before it (its chapter), if any."""
    starts: list[tuple[int, int, str]] = []
    try:
        for bookmark in pdf.get_toc(max_depth=2):
            dest = bookmark.get_dest()
            index = dest.get_index() if dest is not None else None
            title = clean(bookmark.get_title() or "")[:300]
            if index is not None and 0 <= index < count and title:
                starts.append((index, bookmark.level, title))
    except Exception:  # a broken outline shouldn't stop the text being read
        return [None] * count
    starts.sort(key=lambda s: (s[0], s[1]))
    labels: list[str | None] = []
    current = None
    for index in range(count):
        for start, _level, title in starts:
            if start == index:
                current = title
        labels.append(current)
    return labels


def _extract_docx(data: bytes) -> Extraction:
    from docx import Document
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    try:
        document = Document(BytesIO(data))
    except Exception as error:
        raise UnreadableFile("This Word file looks damaged and couldn't be opened.") from error

    # Walk the body in order, starting a new section at each heading.
    sections: list[tuple[str | None, list[str]]] = [(None, [])]
    for child in document.element.body.iterchildren():
        tag = child.tag.rsplit("}", 1)[-1]
        if tag == "p":
            paragraph = Paragraph(child, document)
            text = clean(paragraph.text)
            style = (paragraph.style.name if paragraph.style is not None else "") or ""
            if text and (style.startswith("Heading") or style == "Title"):
                sections.append((text[:300], [text]))
            elif text:
                sections[-1][1].append(text)
        elif tag == "tbl":
            table = Table(child, document)
            for row in table.rows:
                cells = [clean(cell.text) for cell in row.cells]
                # Merged cells repeat; keep each once, in order.
                unique = list(dict.fromkeys(c for c in cells if c))
                if unique:
                    sections[-1][1].append(" | ".join(unique))

    segments: list[Segment] = []
    for label, paragraphs in sections:
        for part in _split("\n\n".join(paragraphs)):
            segments.append(
                Segment(kind="section", number=len(segments) + 1, text=part, label=label)
            )
    if not segments:
        return Extraction(
            segments=[],
            warnings=["No text was found in this Word file. Approving it would add nothing."],
        )
    return Extraction(segments=segments, warnings=[])


def _extract_txt(data: bytes) -> Extraction:
    text, fallback = decode_text(data)
    lines = clean(text).split("\n")
    segments: list[Segment] = []
    start, buffer = 1, []
    size = 0
    for number, line in enumerate(lines, start=1):
        if not buffer and not line.strip():
            start = number + 1
            continue
        buffer.append(line)
        size += len(line) + 1
        if size >= SECTION_CHARS and not line.strip():
            segments.append(Segment(kind="lines", number=start, text=clean("\n".join(buffer))))
            start, buffer, size = number + 1, [], 0
    if any(line.strip() for line in buffer):
        segments.append(Segment(kind="lines", number=start, text=clean("\n".join(buffer))))
    warnings = []
    if fallback:
        warnings.append(
            "This text file isn't UTF-8, so it was read as Windows text. Check accented letters "
            "and symbols came out right."
        )
    if not segments:
        warnings.append("This file has no text. Approving it would add nothing.")
    return Extraction(segments=segments, warnings=warnings)


def _split(text: str) -> list[str]:
    """Text in parts of about SECTION_CHARS, broken at paragraph ends where possible."""
    text = text.strip()
    if not text:
        return []
    parts, current = [], ""
    for paragraph in text.split("\n\n"):
        if current and len(current) + len(paragraph) + 2 > SECTION_CHARS:
            parts.append(current)
            current = paragraph
        else:
            current = f"{current}\n\n{paragraph}" if current else paragraph
    if current:
        parts.append(current)
    return parts
