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
