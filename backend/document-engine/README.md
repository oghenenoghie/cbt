# Document Processing Engine

Responsible for safe ingestion and extraction of school-provided learning materials.

Initial supported inputs:
- PDF and scanned PDF;
- DOCX and PPTX;
- XLSX and CSV;
- TXT;
- JPG, JPEG and PNG.

Processing stages:
1. Validate file type, size and upload ownership.
2. Store the original file with immutable version metadata.
3. Extract text, page/slide/sheet structure and tables.
4. Apply OCR to scanned pages and images.
5. Preserve page/slide/sheet provenance for citations.
6. Report extraction confidence and errors for teacher review.
7. Publish extracted chunks to retrieval only after school approval.

Never silently treat failed or low-quality OCR as complete content.

## Status

Built inside the API (`backend/api/app/documents/`, ADR 0004): upload, storage, and extraction
for PDF, Word (.docx), PowerPoint (.pptx), Excel (.xlsx), CSV and text files, with OCR by
Tesseract (`ocr.py`) for scanned PDF pages, JPEG and PNG photos and picture-only slides, each OCR'd
part carrying a confidence; review and approval; and `python -m app.worker` processing uploads in
the background. It stays a module of the API (a modular monolith) until there's a measured need to
split it out.
