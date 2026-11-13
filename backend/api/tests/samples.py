"""Synthetic learning materials for tests: small PDFs and Word files built in memory.

Nothing here is real school material.
"""

from io import BytesIO


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def make_pdf(pages: list[str | None], outline: list[tuple[str, int]] = ()) -> bytes:
    """A PDF with one page per entry: its text in Helvetica, or no text at all for None (as a
    scanned page would have). `outline` adds bookmarks: (title, page index)."""
    objects: dict[int, bytes] = {}
    page_ids = [5 + 2 * i for i in range(len(pages))]
    outline_ids = [5 + 2 * len(pages) + i for i in range(len(outline))]

    catalog = b"<< /Type /Catalog /Pages 2 0 R"
    if outline:
        catalog += b" /Outlines 4 0 R /PageMode /UseOutlines"
    objects[1] = catalog + b" >>"
    kids = " ".join(f"{pid} 0 R" for pid in page_ids)
    objects[2] = f"<< /Type /Pages /Kids [{kids}] /Count {len(pages)} >>".encode()
    objects[3] = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"
    if outline:
        objects[4] = (
            f"<< /Type /Outlines /First {outline_ids[0]} 0 R /Last {outline_ids[-1]} 0 R "
            f"/Count {len(outline)} >>"
        ).encode()
    for pid, text in zip(page_ids, pages, strict=True):
        lines = (text or "").split("\n") if text else []
        ops = ["BT", "/F1 12 Tf", "14 TL", "72 760 Td"]
        for line in lines:
            ops.append(f"({_escape(line)}) Tj T*")
        ops.append("ET")
        stream = "\n".join(ops).encode() if lines else b""
        objects[pid] = (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Resources << /Font << /F1 3 0 R >> >> /Contents {pid + 1} 0 R >>"
        ).encode()
        objects[pid + 1] = (
            f"<< /Length {len(stream)} >>\nstream\n".encode() + stream + b"\nendstream"
        )
    for i, (oid, (title, page_index)) in enumerate(zip(outline_ids, outline, strict=True)):
        links = ""
        if i > 0:
            links += f" /Prev {outline_ids[i - 1]} 0 R"
        if i < len(outline) - 1:
            links += f" /Next {outline_ids[i + 1]} 0 R"
        objects[oid] = (
            f"<< /Title ({_escape(title)}) /Parent 4 0 R /Dest [{page_ids[page_index]} 0 R /Fit]"
            f"{links} >>"
        ).encode()

    out = BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = {}
    for number in sorted(objects):
        offsets[number] = out.tell()
        out.write(f"{number} 0 obj\n".encode() + objects[number] + b"\nendobj\n")
    xref = out.tell()
    size = max(objects) + 1
    out.write(f"xref\n0 {size}\n0000000000 65535 f \n".encode())
    for number in range(1, size):
        if number in offsets:
            out.write(f"{offsets[number]:010d} 00000 n \n".encode())
        else:
            out.write(b"0000000000 65535 f \n")
    out.write(f"trailer\n<< /Size {size} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    return out.getvalue()


def make_docx(blocks: list[tuple[str, object]]) -> bytes:
    """A Word file from ("heading", text), ("paragraph", text) and ("table", [[cells]]) blocks."""
    from docx import Document

    document = Document()
    for kind, value in blocks:
        if kind == "heading":
            document.add_heading(value, level=1)
        elif kind == "paragraph":
            document.add_paragraph(value)
        elif kind == "table":
            rows = value
            table = document.add_table(rows=len(rows), cols=len(rows[0]))
            for r, row in enumerate(rows):
                for c, cell in enumerate(row):
                    table.cell(r, c).text = cell
    out = BytesIO()
    document.save(out)
    return out.getvalue()


def make_pptx(slides: list[dict]) -> bytes:
    """A presentation: each slide is {"title", "bullets", "notes", "table", "group", "picture"}
    (all optional). "picture" adds a picture of that text (or of placeholder text if True), like
    a slide that is a scanned page."""
    from pptx import Presentation
    from pptx.util import Inches, Pt

    presentation = Presentation()
    for spec in slides:
        layout = presentation.slide_layouts[1 if spec.get("bullets") else 5]
        if not spec.get("title") and spec.get("picture"):
            layout = presentation.slide_layouts[6]  # blank
        slide = presentation.slides.add_slide(layout)
        if spec.get("title") and slide.shapes.title is not None:
            slide.shapes.title.text = spec["title"]
        if spec.get("bullets"):
            body = slide.placeholders[1].text_frame
            body.text = spec["bullets"][0]
            for bullet in spec["bullets"][1:]:
                body.add_paragraph().text = bullet
        if spec.get("table"):
            rows = spec["table"]
            shape = slide.shapes.add_table(
                len(rows), len(rows[0]), Inches(1), Inches(4), Inches(6), Inches(1)
            )
            for r, row in enumerate(rows):
                for c, text in enumerate(row):
                    shape.table.cell(r, c).text = text
        if spec.get("group"):
            group = slide.shapes.add_group_shape()
            for i, text in enumerate(spec["group"]):
                box = group.shapes.add_textbox(
                    Inches(1), Inches(5 + i * 0.5), Inches(4), Inches(0.4)
                )
                box.text_frame.text = text
                box.text_frame.paragraphs[0].font.size = Pt(14)
        if spec.get("picture"):
            picture = (
                make_text_image([spec["picture"]])
                if isinstance(spec["picture"], str)
                else (make_text_image(["Synthetic picture"]))
            )
            slide.shapes.add_picture(BytesIO(picture), 0, 0)
        if spec.get("notes"):
            slide.notes_slide.notes_text_frame.text = spec["notes"]
    out = BytesIO()
    presentation.save(out)
    return out.getvalue()


def make_xlsx(sheets: dict[str, list[list[object]]], hidden: tuple[str, ...] = ()) -> bytes:
    """A workbook with a sheet per entry of rows of values; `hidden` sheets are hidden."""
    from openpyxl import Workbook

    workbook = Workbook()
    workbook.remove(workbook.active)
    for name, rows in sheets.items():
        sheet = workbook.create_sheet(name)
        for row in rows:
            sheet.append(row)
        if name in hidden:
            sheet.sheet_state = "hidden"
    out = BytesIO()
    workbook.save(out)
    return out.getvalue()


def make_text_image(lines: list[str], format: str = "PNG", size: int = 36) -> bytes:
    """A picture of printed lines, as a clean scan or photo would show them."""
    from PIL import Image, ImageDraw, ImageFont

    font = ImageFont.load_default(size=size)
    width = max(1200, 60 + int(size * 0.62 * max(len(line) for line in lines)))
    image = Image.new("L", (width, 120 + len(lines) * int(size * 2.4)), 255)
    draw = ImageDraw.Draw(image)
    for index, line in enumerate(lines):
        draw.text((60, 60 + index * int(size * 2.4)), line, fill=0, font=font)
    out = BytesIO()
    image.convert("RGB").save(out, format)
    return out.getvalue()


def make_scanned_pdf(pages: list[list[str]]) -> bytes:
    """A PDF whose pages are only pictures of text, as a scanner makes: no text layer."""
    from PIL import Image

    images = [Image.open(BytesIO(make_text_image(lines))).convert("RGB") for lines in pages]
    out = BytesIO()
    images[0].save(out, "PDF", save_all=True, append_images=images[1:], resolution=150)
    return out.getvalue()
