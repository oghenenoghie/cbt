"""Reading uploaded files: what they are, and the text in them (ADR 0004).

`identify` decides what a file is from its content, not its name, and refuses what we can't or
won't read. `extract` pulls out text in segments that record where each came from (a PDF page, a
Word section, a slide, a sheet, a range of lines or rows, a photo), with warnings for anything a
reviewer must know: a page with no readable text is flagged, never quietly treated as complete,
and text read from a picture (OCR, `app/documents/ocr.py`) carries its confidence.

Supported: PDF (scanned pages are read with OCR when Tesseract is installed), Word (.docx),
PowerPoint (.pptx), Excel (.xlsx), CSV, plain text, and JPEG or PNG photos (OCR).
"""

import csv
import re
import zipfile
from dataclasses import dataclass, field
from datetime import date, datetime, time
from io import BytesIO, StringIO

from app.core.config import get_settings
from app.documents import ocr

CONTENT_TYPES = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "csv": "text/csv; charset=utf-8",
    "txt": "text/plain; charset=utf-8",
    "jpeg": "image/jpeg",
    "png": "image/png",
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
    # "page" (PDF), "section" (Word), "slide" (PowerPoint), "sheet" (Excel), "rows" (CSV),
    # "lines" (text) or "image" (a photo).
    kind: str
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


def _pages(numbers: list[int], word: str = "Page") -> str:
    return (f"{word} " if len(numbers) == 1 else f"{word}s ") + ", ".join(str(n) for n in numbers)


def _percent(confidence: float | None) -> str:
    return f"{round((confidence or 0) * 100)}%"


# --- What is it? ---------------------------------------------------------------------------------


def identify(filename: str, data: bytes) -> str:
    """The file's kind (a key of CONTENT_TYPES), from its content. Raises UnreadableFile."""
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
        if not ocr.available():
            raise UnreadableFile(
                "Photos and scanned images need their text read from the picture (OCR), which "
                "isn't set up on this server. Upload a PDF or Word file with the text in it."
            )
        return "jpeg" if data.startswith(b"\xff\xd8\xff") else "png"
    if data.startswith((b"\xd0\xcf\x11\xe0", b"{\\rtf")):
        raise UnreadableFile(
            "Older Office files (.doc, .ppt, .xls) and rich-text files can't be read. Save it as "
            ".docx, .pptx, .xlsx or PDF first."
        )
    name = filename.lower()
    if name.endswith(".csv") and _looks_like_text(data):
        return "csv"
    if name.endswith((".txt", ".text", ".md")) and _looks_like_text(data):
        return "txt"
    raise UnreadableFile(
        "This kind of file isn't supported. Upload a PDF, Word, PowerPoint, Excel, CSV or text "
        "file, or a JPEG or PNG photo."
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
            "Files with macros can't be uploaded. Save it as an ordinary .docx, .pptx or .xlsx, "
            "or as PDF, first."
        )
    if "wordprocessingml.document.main" in types:
        return "docx"
    if "presentationml.presentation.main" in types or "presentationml.slideshow.main" in types:
        return "pptx"
    if "spreadsheetml.sheet.main" in types:
        return "xlsx"
    if "template.main" in types:
        raise UnreadableFile(
            "Templates (.dotx, .potx, .xltx) can't be uploaded. Save it as an ordinary document, "
            "presentation or workbook first."
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
    readers = {
        "pdf": _extract_pdf,
        "docx": _extract_docx,
        "pptx": _extract_pptx,
        "xlsx": _extract_xlsx,
        "csv": _extract_csv,
        "txt": _extract_txt,
        "jpeg": _extract_image,
        "png": _extract_image,
    }
    if kind not in readers:
        raise UnreadableFile("This kind of file isn't supported.")
    return readers[kind](data)


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
    reading = ocr.available()
    skipped: list[int] = []
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
        read = 0
        for index in range(count):
            page = pdf[index]
            textpage = page.get_textpage()
            text = clean(textpage.get_text_range())
            textpage.close()
            segment = Segment(kind="page", number=index + 1, text=text, label=chapters[index])
            if len(text) < MIN_PAGE_CHARS:
                if reading and read < settings.ocr_max_pages:
                    # No text layer: the page is probably a scan, so read its picture.
                    image = page.render(scale=settings.ocr_dpi / 72, grayscale=True).to_pil()
                    _read_picture(segment, image)
                    read += 1
                elif reading:
                    skipped.append(segment.number)
                    segment.flags.append("no_text")
                else:
                    segment.flags.append("no_text")
            page.close()
            segments.append(segment)
    finally:
        pdf.close()

    warnings = []
    blank = [s.number for s in segments if "no_text" in s.flags]
    if len(blank) == len(segments):
        warnings.append(
            "No text could be read from this PDF, even from pictures of its pages. Approving it "
            "would add nothing."
            if reading
            else "No readable text was found: this PDF looks scanned, and reading scanned pages "
            "(OCR) isn't set up on this server. Approving it would add nothing."
        )
    elif blank:
        warnings.append(
            f"{_pages(blank)} have no readable text (they may be scanned pictures or diagrams). "
            "Anything on them won't be used."
            if len(blank) > 1
            else f"{_pages(blank)} has no readable text (it may be a scanned picture or a "
            "diagram). Anything on it won't be used."
        )
        if not reading:
            warnings.append(
                "Scanned pages can't be read on this server, because OCR (Tesseract) isn't set up."
            )
    if skipped:
        warnings.append(
            f"At most {settings.ocr_max_pages} scanned pages are read per file, so "
            f"{_pages(skipped).lower()} {'wasn' if len(skipped) == 1 else 'weren'}'t. Split the "
            "file to read the rest."
        )
    warnings += _ocr_warnings(segments, "Page")
    return Extraction(segments=segments, warnings=warnings)


def _read_picture(segment: Segment, image) -> None:
    """Fill `segment` with the text OCR finds in `image`, its confidence, and its flags."""
    settings = get_settings()
    try:
        result = ocr.read_image(image)
    except ocr.OcrError:
        segment.flags.append("no_text")
        return
    segment.method = "ocr"
    segment.text = clean(result.text)
    segment.confidence = result.confidence
    if len(segment.text) < MIN_PAGE_CHARS:
        segment.flags.append("no_text")
    elif (result.confidence or 0) < settings.ocr_min_confidence:
        segment.flags.append("low_confidence")


CHECK_OCR = "OCR can misread words, especially in poor scans and handwriting."


def _ocr_warnings(segments: list[Segment], word: str) -> list[str]:
    """What the reviewer must know about text read from pictures."""
    read = [s for s in segments if s.method == "ocr" and "no_text" not in s.flags]
    if not read:
        return []
    warnings = []
    numbers = [s.number for s in read]
    warnings.append(
        f"{_pages(numbers, word)} {'was' if len(numbers) == 1 else 'were'} read from a picture "
        f"(OCR). Check the text against the file: {CHECK_OCR}"
    )
    low = [s for s in read if "low_confidence" in s.flags]
    if low:
        details = ", ".join(f"{s.number} ({_percent(s.confidence)})" for s in low)
        warnings.append(
            f"{word}s read with low confidence won't be used for AI drafts: {details}. Upload a "
            "clearer copy to use them."
            if len(low) > 1
            else f"{word} {details} was read with low confidence, so it won't be used for AI "
            "drafts. Upload a clearer copy to use it."
        )
    return warnings


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


def _extract_pptx(data: bytes) -> Extraction:
    from pptx import Presentation

    settings = get_settings()
    try:
        presentation = Presentation(BytesIO(data))
    except Exception as error:
        raise UnreadableFile(
            "This PowerPoint file looks damaged and couldn't be opened."
        ) from error
    slides = list(presentation.slides)
    if len(slides) > settings.document_max_pages:
        raise UnreadableFile(
            f"This presentation has {len(slides)} slides; the most we take is "
            f"{settings.document_max_pages}. Split it into parts."
        )
    reading = ocr.available()
    read = 0
    segments: list[Segment] = []
    for number, slide in enumerate(slides, start=1):
        title_shape = slide.shapes.title
        title = clean(title_shape.text_frame.text) if title_shape is not None else ""
        parts = [title] if title else []
        for shape in _reading_order(slide.shapes):
            if title_shape is not None and shape.shape_id == title_shape.shape_id:
                continue
            parts.extend(_shape_text(shape))
        if slide.has_notes_slide:
            notes = clean(slide.notes_slide.notes_text_frame.text or "")
            if notes:
                parts.append(f"Speaker notes:\n{notes}")
        text = clean("\n".join(p for p in parts if p))
        segment = Segment(kind="slide", number=number, text=text, label=title[:300] or None)
        if len(text) < MIN_PAGE_CHARS:
            picture = _largest_picture(slide.shapes) if reading else None
            if picture is not None and read < settings.ocr_max_pages:
                # A slide that is only a picture, such as a scanned page: read the picture.
                _read_picture(segment, picture)
                read += 1
                if title and segment.text:
                    segment.text = clean(f"{title}\n{segment.text}")
            else:
                segment.flags.append("no_text")
        segments.append(segment)

    warnings = []
    blank = [s.number for s in segments if "no_text" in s.flags]
    if not segments or len(blank) == len(segments):
        warnings.append("No text was found in this presentation. Approving it would add nothing.")
    elif blank:
        warnings.append(
            f"{_pages(blank, 'Slide')} {'has' if len(blank) == 1 else 'have'} no text (only "
            "pictures or diagrams, perhaps). Anything on "
            f"{'it' if len(blank) == 1 else 'them'} won't be used."
        )
    warnings += _ocr_warnings(segments, "Slide")
    return Extraction(segments=segments, warnings=warnings)


def _largest_picture(shapes):
    """The biggest picture on a slide, opened for OCR, or None."""
    from PIL import Image
    from pptx.enum.shapes import MSO_SHAPE_TYPE

    settings = get_settings()
    best, best_area = None, 0
    for shape in shapes:
        if shape.shape_type != MSO_SHAPE_TYPE.PICTURE:
            continue
        area = (shape.width or 0) * (shape.height or 0)
        if area > best_area:
            best, best_area = shape, area
    if best is None:
        return None
    try:
        image = Image.open(BytesIO(best.image.blob))
        width, height = image.size
        if width * height > settings.image_max_megapixels * 1_000_000:
            return None
        image.load()
        return image
    except Exception:  # an unreadable picture is just a slide without text
        return None


def _reading_order(shapes) -> list:
    """Shapes top to bottom, then left to right, as a person reads a slide."""
    return sorted(shapes, key=lambda shape: (shape.top or 0, shape.left or 0))


def _shape_text(shape) -> list[str]:
    """The text in a shape: its text, a table's rows, or a group's shapes in reading order."""
    from pptx.enum.shapes import MSO_SHAPE_TYPE

    if shape.shape_type == MSO_SHAPE_TYPE.GROUP:
        return [text for child in _reading_order(shape.shapes) for text in _shape_text(child)]
    if getattr(shape, "has_table", False) and shape.has_table:
        rows = []
        for row in shape.table.rows:
            cells = list(dict.fromkeys(clean(cell.text) for cell in row.cells if clean(cell.text)))
            if cells:
                rows.append(" | ".join(cells))
        return rows
    if getattr(shape, "has_text_frame", False) and shape.has_text_frame:
        text = clean(shape.text_frame.text)
        return [text] if text else []
    return []


def _cell(value) -> str:
    """A spreadsheet value as people would read it."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, float):
        return str(int(value)) if value.is_integer() else f"{value:g}"
    if isinstance(value, datetime):
        return value.date().isoformat() if value.time() == time() else value.isoformat(" ")
    if isinstance(value, date | time):
        return value.isoformat()
    return clean(str(value)).replace("\n", " ")


def _table_parts(rows: list[tuple[int, list[str]]]) -> list[tuple[int, int, str]]:
    """Rows of a table as text parts of about SECTION_CHARS: (first row, last row, text).
    Every part after the first repeats the first row, which usually names the columns."""
    if not rows:
        return []
    header = " | ".join(rows[0][1])
    parts: list[tuple[int, int, str]] = []
    lines: list[str] = []
    first = previous = rows[0][0]
    size = 0
    for number, cells in rows:
        line = " | ".join(cells)
        if lines and size + len(line) > SECTION_CHARS:
            parts.append((first, previous, "\n".join(lines)))
            lines, size, first = [header], len(header), number
        lines.append(line)
        size += len(line) + 1
        previous = number
    parts.append((first, previous, "\n".join(lines)))
    return parts


def _trimmed(values) -> list[str]:
    cells = [_cell(v) for v in values]
    while cells and not cells[-1]:
        cells.pop()
    return cells


def _extract_xlsx(data: bytes) -> Extraction:
    from openpyxl import load_workbook

    try:
        workbook = load_workbook(BytesIO(data), read_only=True, data_only=True)
    except Exception as error:
        raise UnreadableFile("This Excel file looks damaged and couldn't be opened.") from error
    segments: list[Segment] = []
    hidden: list[str] = []
    try:
        for number, sheet in enumerate(workbook.worksheets, start=1):
            if sheet.sheet_state != "visible":
                # Hidden sheets often hold lookups or answers: never use them as evidence.
                hidden.append(sheet.title)
                continue
            rows = []
            for row_number, values in enumerate(sheet.iter_rows(values_only=True), start=1):
                cells = _trimmed(values)
                if any(cells):
                    rows.append((row_number, cells))
            parts = _table_parts(rows)
            for first, last, text in parts:
                label = sheet.title if len(parts) == 1 else f"{sheet.title}, rows {first}-{last}"
                segments.append(Segment(kind="sheet", number=number, text=text, label=label[:300]))
    finally:
        workbook.close()

    warnings = []
    if hidden:
        names = ", ".join(f"“{name}”" for name in hidden)
        warnings.append(
            f"Hidden sheets were left out: {names}. Unhide a sheet in Excel and upload it again "
            "to use it."
        )
    if not segments:
        warnings.append("No data was found in this workbook. Approving it would add nothing.")
    return Extraction(segments=segments, warnings=warnings)


def _extract_csv(data: bytes) -> Extraction:
    text, fallback = decode_text(data)
    sample = text[:8192]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    rows = []
    try:
        for row_number, values in enumerate(csv.reader(StringIO(text), dialect), start=1):
            cells = _trimmed(values)
            if any(cells):
                rows.append((row_number, cells))
    except csv.Error as error:
        raise UnreadableFile(
            "This CSV file couldn't be read: check it opens in a spreadsheet."
        ) from error
    segments = [
        Segment(kind="rows", number=first, text=part_text, label=f"rows {first}-{last}")
        for first, last, part_text in _table_parts(rows)
    ]
    warnings = []
    if fallback:
        warnings.append(
            "This file isn't UTF-8, so it was read as Windows text. Check accented letters and "
            "symbols came out right."
        )
    if not segments:
        warnings.append("This file has no data. Approving it would add nothing.")
    return Extraction(segments=segments, warnings=warnings)


def _extract_image(data: bytes) -> Extraction:
    from PIL import Image, ImageOps, UnidentifiedImageError

    settings = get_settings()
    try:
        image = Image.open(BytesIO(data))
        width, height = image.size
        if width * height > settings.image_max_megapixels * 1_000_000:
            raise UnreadableFile(
                f"This photo is larger than {settings.image_max_megapixels} million pixels. "
                "Make it smaller and upload it again."
            )
        image = ImageOps.exif_transpose(image)
        image.load()
    except UnreadableFile:
        raise
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as error:
        raise UnreadableFile("This picture looks damaged and couldn't be opened.") from error
    if not ocr.available():
        raise UnreadableFile("Reading photos (OCR) isn't set up on this server.")
    segment = Segment(kind="image", number=1, text="")
    _read_picture(segment, image)
    if "no_text" in segment.flags:
        warnings = [
            "No text could be read from this picture. Approving it would add nothing; a sharper, "
            "well-lit photo taken straight on may work better."
        ]
    elif "low_confidence" in segment.flags:
        warnings = [
            f"The text was read from the photo (OCR) with low confidence "
            f"({_percent(segment.confidence)}), so it won't be used for AI drafts. A sharper, "
            "well-lit photo taken straight on may work better."
        ]
    else:
        warnings = [
            f"The text was read from the photo (OCR). Check it against the photo: {CHECK_OCR}"
        ]
    return Extraction(segments=[segment], warnings=warnings)


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
