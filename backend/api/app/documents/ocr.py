"""Reading text from pictures with Tesseract (ADR 0004, decision 9).

Tesseract runs on our own server, so school material never leaves it and there's no per-page
cost. It is good on clear print and weak on handwriting and poor photos, so every result carries
a confidence (the average of Tesseract's confidence in each word, weighted by length), and text
read with low confidence is flagged for the reviewer and never used as AI evidence.

Tesseract runs as a separate program on an image we have already decoded and re-encoded as PNG,
so it never parses the uploaded file itself. It gets one thread and a time limit.
"""

import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from io import BytesIO
from typing import TYPE_CHECKING

from app.core.config import get_settings

if TYPE_CHECKING:
    from PIL.Image import Image

_LANGUAGES = re.compile(r"^[A-Za-z_]+(\+[A-Za-z_]+)*$")
# Pictures wider or taller than this are scaled down first: more pixels only slow Tesseract.
MAX_SIDE = 6000


class OcrError(Exception):
    """Tesseract couldn't read the picture, with a message for the person who uploaded it."""


@dataclass
class OcrResult:
    text: str
    # From 0 to 1; None when no words were found.
    confidence: float | None


def available() -> bool:
    """Whether OCR is turned on and Tesseract is installed."""
    settings = get_settings()
    return settings.ocr_enabled and shutil.which(settings.tesseract_cmd) is not None


def parse_tsv(tsv: str) -> OcrResult:
    """Text and confidence from Tesseract's TSV output.

    Each word is a row at level 5 with its block, paragraph and line numbers and a confidence
    from 0 to 100 (-1 for rows that aren't words). Lines are rebuilt in order, with a blank line
    between paragraphs."""
    lines: dict[tuple[int, int, int], list[str]] = {}
    weighted = 0.0
    letters = 0
    rows = tsv.splitlines()
    for row in rows[1:]:
        cells = row.split("\t")
        if len(cells) < 12 or cells[0] != "5":
            continue
        text = cells[11].strip()
        try:
            confidence = float(cells[10])
        except ValueError:
            continue
        if not text or confidence < 0:
            continue
        key = (int(cells[2]), int(cells[3]), int(cells[4]))
        lines.setdefault(key, []).append(text)
        weighted += confidence * len(text)
        letters += len(text)
    parts: list[str] = []
    previous: tuple[int, int] | None = None
    for (block, paragraph, _line), words in sorted(lines.items()):
        if previous is not None and previous != (block, paragraph):
            parts.append("")
        parts.append(" ".join(words))
        previous = (block, paragraph)
    return OcrResult(
        text="\n".join(parts).strip(),
        confidence=round(weighted / letters / 100, 3) if letters else None,
    )


def _prepare(image: "Image") -> bytes:
    """The picture as greyscale PNG, scaled down if it's huge."""
    image = image.convert("L")
    if max(image.size) > MAX_SIDE:
        image.thumbnail((MAX_SIDE, MAX_SIDE))
    buffer = BytesIO()
    image.save(buffer, "PNG")
    return buffer.getvalue()


def read_image(image: "Image") -> OcrResult:
    """The text in a picture. Raises OcrError if Tesseract fails or takes too long."""
    settings = get_settings()
    languages = settings.ocr_languages.strip() or "eng"
    if not _LANGUAGES.match(languages):
        raise OcrError("OCR is set up with a language list it can't use.")
    command = [settings.tesseract_cmd, "stdin", "stdout", "-l", languages, "--psm", "3", "tsv"]
    environment = {"PATH": os.environ.get("PATH", ""), "OMP_THREAD_LIMIT": "1"}
    try:
        result = subprocess.run(
            command,
            input=_prepare(image),
            capture_output=True,
            timeout=settings.ocr_timeout_seconds,
            env=environment,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        raise OcrError("Reading this picture took too long.") from error
    except OSError as error:
        raise OcrError("OCR isn't working on this server.") from error
    if result.returncode != 0:
        raise OcrError("The picture couldn't be read.")
    return parse_tsv(result.stdout.decode("utf-8", errors="replace"))
