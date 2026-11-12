"""More kinds of learning material (ADR 0004 stages B and C): PowerPoint, Excel and CSV, and
text read from pictures (OCR) in scanned PDFs, photos and picture-only slides.

Tests marked `needs_tesseract` run the real Tesseract. They are skipped where it isn't
installed, unless REQUIRE_OCR is set (as in CI), when they run and fail instead. The others
stand in for OCR so they are exact. All material is synthetic, built by tests/samples.py.
"""

import os

import pytest
import test_documents
from samples import make_pdf, make_pptx, make_scanned_pdf, make_text_image, make_xlsx
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_documents import act, get, segments, upload, uploaded

from app.ai.fake import FakeProvider
from app.ai.provider import use_provider
from app.core.config import get_settings
from app.documents import ocr
from app.documents.ocr import OcrResult, parse_tsv
from app.models import DocumentVersion

school = test_documents.school

needs_tesseract = pytest.mark.skipif(
    not ocr.available() and not os.environ.get("REQUIRE_OCR"),
    reason="Tesseract isn't installed (CI sets REQUIRE_OCR, so it runs there)",
)


@pytest.fixture
def fake_ocr(monkeypatch):
    """OCR that returns the next of `results` for each picture, without Tesseract."""
    results: list[OcrResult] = []
    monkeypatch.setattr(ocr, "available", lambda: True)
    monkeypatch.setattr(ocr, "read_image", lambda image: results.pop(0))
    return results


def latest(who, document) -> dict:
    return get(who, document["id"])["latest"]


# --- PowerPoint, Excel and CSV ---------------------------------------------------------------


def test_powerpoint_slides_are_read_with_titles_tables_groups_and_notes(school) -> None:
    deck = make_pptx(
        [
            {
                "title": "Cells",
                "bullets": [
                    "The cell is the basic unit of life.",
                    "The nucleus controls the cell.",
                ],
                "notes": "Ask the class to draw a cell.",
            },
            {
                "title": "Parts of a cell",
                "table": [["Part", "Job"], ["Nucleus", "Controls the cell"]],
                "group": ["Mitochondria release energy.", "Ribosomes make proteins."],
            },
            {"title": "A diagram"},
        ]
    )
    created = uploaded(school.teacher, school.science, data=deck, filename="cells.pptx")

    version = latest(school.teacher, created)
    assert (version["status"], version["kind"]) == ("extracted", "pptx")
    assert version["content_type"].endswith("presentationml.presentation")
    slides = segments(school.teacher, created["id"])["segments"]
    assert [(s["kind"], s["number"], s["label"], s["flags"]) for s in slides] == [
        ("slide", 1, "Cells", []),
        ("slide", 2, "Parts of a cell", []),
        ("slide", 3, "A diagram", ["no_text"]),
    ]
    assert slides[0]["text"] == (
        "Cells\nThe cell is the basic unit of life.\nThe nucleus controls the cell.\n"
        "Speaker notes:\nAsk the class to draw a cell."
    )
    assert "Part | Job\nNucleus | Controls the cell" in slides[1]["text"]
    assert "Mitochondria release energy.\nRibosomes make proteins." in slides[1]["text"]
    assert version["warnings"] == [
        "Slide 3 has no text (only pictures or diagrams, perhaps). Anything on it won't be used."
    ]


def test_excel_sheets_are_read_and_hidden_sheets_left_out(school) -> None:
    workbook = make_xlsx(
        {
            "Planets": [
                ["Planet", "Moons", "Has rings"],
                ["Earth", 1, False],
                ["Saturn", 146.0, True],
            ],
            "Empty": [],
            "Answers": [["Question 1", "B"]],
        },
        hidden=("Answers",),
    )
    created = uploaded(school.teacher, school.science, data=workbook, filename="planets.xlsx")

    version = latest(school.teacher, created)
    assert version["kind"] == "xlsx"
    sheets = segments(school.teacher, created["id"])["segments"]
    assert [(s["kind"], s["number"], s["label"]) for s in sheets] == [("sheet", 1, "Planets")]
    assert sheets[0]["text"] == "Planet | Moons | Has rings\nEarth | 1 | FALSE\nSaturn | 146 | TRUE"
    # Hidden sheets can hold lookups or answers: they're never read.
    assert "Question 1" not in str(sheets)
    assert version["warnings"] == [
        "Hidden sheets were left out: “Answers”. Unhide a sheet in Excel and upload it again "
        "to use it."
    ]


def test_long_sheets_are_split_with_the_header_repeated(school) -> None:
    rows = [["Element", "Symbol", "Fact"]] + [
        [f"Element {n}", f"E{n}", "A synthetic fact about this element, for testing. " * 2]
        for n in range(1, 61)
    ]
    created = uploaded(
        school.teacher, school.science, data=make_xlsx({"Table": rows}), filename="table.xlsx"
    )

    parts = segments(school.teacher, created["id"])["segments"]
    assert len(parts) > 1
    assert parts[0]["label"].startswith("Table, rows 1-")
    for part in parts[1:]:
        assert part["text"].startswith("Element | Symbol | Fact\n")
    assert sum(p["text"].count("\nElement ") for p in parts) + 1 == 61


def test_csv_files_are_read_whatever_their_separator(school) -> None:
    data = b"Planet;Moons\nEarth;1\nMars;2\n"
    created = uploaded(school.teacher, school.science, data=data, filename="planets.csv")

    version = latest(school.teacher, created)
    assert (version["kind"], version["warnings"]) == ("csv", [])
    rows = segments(school.teacher, created["id"])["segments"]
    assert [(r["kind"], r["number"], r["text"]) for r in rows] == [
        ("rows", 1, "Planet | Moons\nEarth | 1\nMars | 2")
    ]

    windows = "Name,Note\nZoë,café\n".encode("cp1252")
    created = uploaded(school.teacher, school.science, data=windows, filename="notes.csv")
    assert "isn't UTF-8" in latest(school.teacher, created)["warnings"][0]
    assert "Zoë | café" in segments(school.teacher, created["id"])["segments"][0]["text"]


def test_slide_and_sheet_evidence_is_located_for_ai_drafts(school) -> None:
    deck = make_pptx(
        [{"title": "Cells", "bullets": ["The nucleus controls the activities of the cell."]}]
    )
    created = uploaded(school.teacher, school.science, data=deck, filename="cells.pptx")
    act(school.teacher, created["id"], "versions/1/approve", {})

    with use_provider(FakeProvider()):
        response = school.teacher.client.post(
            "/api/v1/ai/requests",
            json={
                "subject_id": school.science.id,
                "objective": "nucleus",
                "question_types": ["true_false"],
            },
            headers=school.teacher.headers,
        )
    assert response.status_code == 202, response.text
    assert response.json()["sources"][0]["location"] == "slide 1 (Cells)"


# --- OCR --------------------------------------------------------------------------------------


def test_tesseract_output_is_read_into_lines_and_a_confidence() -> None:
    header = "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext"
    rows = [
        "1\t1\t0\t0\t0\t0\t0\t0\t100\t100\t-1\t",
        "5\t1\t1\t1\t1\t1\t0\t0\t10\t10\t90\tCells",
        "5\t1\t1\t1\t1\t2\t0\t0\t10\t10\t80\tgrow",
        "5\t1\t1\t1\t2\t1\t0\t0\t10\t10\t60\tfast",
        "5\t1\t2\t1\t1\t1\t0\t0\t10\t10\t-1\t",
        "5\t1\t2\t1\t1\t2\t0\t0\t10\t10\t100\tEnd",
    ]
    result = parse_tsv("\n".join([header, *rows]))

    assert result.text == "Cells grow\nfast\n\nEnd"
    # Weighted by length: (90*5 + 80*4 + 60*4 + 100*3) / 16 letters.
    assert result.confidence == round((90 * 5 + 80 * 4 + 60 * 4 + 100 * 3) / 16 / 100, 3)
    assert parse_tsv(header) == OcrResult(text="", confidence=None)


def test_scanned_pages_are_read_and_low_confidence_ones_flagged(school, fake_ocr, monkeypatch):
    fake_ocr += [
        OcrResult("Matter is anything that has mass and takes up space.", 0.94),
        OcrResult("Energy can change frm one forn to anothr.", 0.41),
    ]
    scan = make_pdf(["Contents\nThis page has its own text layer.", None, None])
    created = uploaded(school.teacher, school.science, data=scan, filename="scan.pdf")

    version = latest(school.teacher, created)
    pages = segments(school.teacher, created["id"])["segments"]
    assert [(p["method"], p["confidence"], p["flags"]) for p in pages] == [
        ("text", None, []),
        ("ocr", 0.94, []),
        ("ocr", 0.41, ["low_confidence"]),
    ]
    assert pages[1]["text"] == "Matter is anything that has mass and takes up space."
    assert version["warnings"] == [
        "Pages 2, 3 were read from a picture (OCR). Check the text against the file: OCR can "
        "misread words, especially in poor scans and handwriting.",
        "Page 3 (41%) was read with low confidence, so it won't be used for AI drafts. Upload a "
        "clearer copy to use it.",
    ]

    # Approved, the low-confidence page is still never evidence.
    act(school.teacher, created["id"], "versions/1/approve", {"acknowledge_warnings": True})
    provider = FakeProvider()
    with use_provider(provider):
        response = school.teacher.client.post(
            "/api/v1/ai/requests",
            json={"subject_id": school.science.id, "question_types": ["true_false"]},
            headers=school.teacher.headers,
        )
    assert response.status_code == 202, response.text
    request = response.json()
    assert [s["location"] for s in request["sources"]] == ["page 1", "page 2"]
    assert "1 part read from pictures with low confidence wasn't used." in request["notes"]
    assert "frm one forn" not in " ".join(s.text for s in provider.briefs[0].sources)


def test_ocr_limits_and_failures_leave_pages_flagged(school, fake_ocr, monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "ocr_max_pages", 1)
    fake_ocr += [OcrResult("", None)]
    created = uploaded(
        school.teacher, school.science, data=make_pdf([None, None]), filename="a.pdf"
    )

    version = latest(school.teacher, created)
    assert [p["flags"] for p in segments(school.teacher, created["id"])["segments"]] == [
        ["no_text"],
        ["no_text"],
    ]
    assert (
        "At most 1 scanned pages are read per file, so page 2 wasn't. Split the file to read the rest."
        in version["warnings"]
    )

    def broken(image):
        raise ocr.OcrError("Reading this picture took too long.")

    monkeypatch.setattr(ocr, "read_image", broken)
    created = uploaded(school.teacher, school.science, data=make_pdf([None]), filename="b.pdf")
    assert segments(school.teacher, created["id"])["segments"][0]["flags"] == ["no_text"]


def test_without_ocr_photos_are_refused_and_scans_explained(school, monkeypatch) -> None:
    monkeypatch.setattr(get_settings(), "ocr_enabled", False)
    response = upload(
        school.teacher, school.science, data=make_text_image(["Synthetic"]), filename="photo.png"
    )
    assert response.status_code == 422
    assert "isn't set up on this server" in response.json()["detail"]

    created = uploaded(school.teacher, school.science, data=make_pdf(["Page one has text.", None]))
    assert (
        "Scanned pages can't be read on this server, because OCR (Tesseract) isn't set up."
        in latest(school.teacher, created)["warnings"]
    )


def test_oversized_and_damaged_photos_fail_with_a_reason(school, fake_ocr, monkeypatch, db):
    monkeypatch.setattr(get_settings(), "image_max_megapixels", 0)
    created = uploaded(
        school.teacher, school.science, data=make_text_image(["Big"]), filename="big.png"
    )
    version = latest(school.teacher, created)
    assert version["status"] == "failed"
    assert "larger than 0 million pixels" in version["error"]

    monkeypatch.setattr(get_settings(), "image_max_megapixels", 40)
    damaged = b"\x89PNG\r\n\x1a\n" + b"not really a picture"
    created = uploaded(school.teacher, school.science, data=damaged, filename="bad.png")
    assert (
        latest(school.teacher, created)["error"]
        == "This picture looks damaged and couldn't be opened."
    )


@needs_tesseract
def test_photos_are_read_with_tesseract(school, db: Session) -> None:
    photo = make_text_image(
        ["Photosynthesis takes place in the chloroplasts.", "Plants need light and water."],
        format="JPEG",
    )
    created = uploaded(school.teacher, school.science, data=photo, filename="board.jpg")

    version = latest(school.teacher, created)
    assert (version["status"], version["kind"], version["content_type"]) == (
        "extracted",
        "jpeg",
        "image/jpeg",
    )
    (segment,) = segments(school.teacher, created["id"])["segments"]
    assert (segment["kind"], segment["method"], segment["flags"]) == ("image", "ocr", [])
    assert "Photosynthesis takes place in the chloroplasts." in segment["text"]
    assert segment["confidence"] > 0.8
    assert version["warnings"][0].startswith("The text was read from the photo (OCR).")
    # The warning must be acknowledged before approving, as for any warning.
    assert act(school.teacher, created["id"], "versions/1/approve", {}).status_code == 409
    response = act(
        school.teacher, created["id"], "versions/1/approve", {"acknowledge_warnings": True}
    )
    assert response.status_code == 200


@needs_tesseract
def test_scanned_pdfs_and_picture_slides_are_read_with_tesseract(school) -> None:
    scan = make_scanned_pdf(
        [["Matter is anything that has mass."], ["Energy is the ability to do work."]]
    )
    created = uploaded(school.teacher, school.science, data=scan, filename="scan.pdf")
    pages = segments(school.teacher, created["id"])["segments"]
    assert [p["method"] for p in pages] == ["ocr", "ocr"]
    assert "Energy is the ability to do work." in pages[1]["text"]

    deck = make_pptx([{"picture": "The heart pumps blood around the body."}])
    created = uploaded(school.teacher, school.science, data=deck, filename="scan.pptx")
    (slide,) = segments(school.teacher, created["id"])["segments"]
    assert (slide["kind"], slide["method"]) == ("slide", "ocr")
    assert "The heart pumps blood around the body." in slide["text"]


@needs_tesseract
def test_low_confidence_photos_are_flagged(school, monkeypatch, db: Session) -> None:
    monkeypatch.setattr(get_settings(), "ocr_min_confidence", 0.999)
    created = uploaded(
        school.teacher,
        school.science,
        data=make_text_image(["The heart pumps blood."]),
        filename="p.png",
    )
    (segment,) = segments(school.teacher, created["id"])["segments"]
    assert segment["flags"] == ["low_confidence"]
    assert "low confidence" in latest(school.teacher, created)["warnings"][0]
    stored = db.scalar(select(DocumentVersion).where(DocumentVersion.document_id == created["id"]))
    assert stored.kind == "png"
