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

Stage A is built inside the API (`backend/api/app/documents/`, ADR 0004): upload, storage,
extraction for PDF with a text layer, Word (.docx) and text files, review and approval, with
`python -m app.worker` processing uploads in the background. PowerPoint, Excel and CSV come next,
then OCR with Tesseract for scanned pages and images. It stays a module of the API (a modular
monolith) until there's a measured need to split it out.
