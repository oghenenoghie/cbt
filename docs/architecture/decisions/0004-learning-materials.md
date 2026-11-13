# ADR 0004: Learning materials

- **Status:** Accepted. Stages A to D are built.
- **Date:** 2026-11-08
- **Implemented in:** `backend/api/app/models/documents.py`, `backend/api/app/documents/` (OCR in `ocr.py`), `backend/api/app/core/storage.py`, `backend/api/app/worker.py` (migrations `0011_documents`, `0013_more_material_kinds`); the web screens in `apps/web` (`/materials`)

## Context

The exam workflow is complete (ADR 0003). The product's next step, and its point, is questions drafted by AI from a school's own materials, never from the model's general knowledge (Phase 4). That needs the materials first: uploaded, read reliably, with every piece of text traceable to where it came from, and checked by a person before anything relies on it.

The product docs fix the inputs (PDF, scanned PDF, Word, PowerPoint, Excel, CSV, text, JPG and PNG), the processing stages (validate, store immutably, extract with page, slide and sheet provenance, OCR scans, report confidence and errors, publish to retrieval only after approval) and one hard rule: never treat failed or low-quality OCR as complete content. They didn't say who uploads and approves, which OCR to use, or who sees what. Those were settled with the user before building.

The work is built in stages, each its own change:

- **A. Upload, storage, extraction and review** for PDF (with a text layer), Word (.docx) and plain text, through the API. (Built.)
- **B. PowerPoint, Excel and CSV**, with slide and sheet provenance. (Built.)
- **C. Scanned pages and images (OCR)**, with a confidence for each page. (Built.)
- **D. Web screens** for uploading, reviewing and approving. (Built: `apps/web`, `/materials`.)

## Decisions

1. **Subject staff upload and approve, including their own uploads.**
   - School admins, and teachers who teach the subject to any class, can upload a subject's materials and approve them: the same people who can use its question bank (ADR 0003, decision 5).
   - Approving means "the extracted text is faithful to the file", not "this is good teaching material", so approving your own upload is allowed. (Exams are different: nobody approves an exam they prepared.)
   - Students can't reach materials at all.
2. **Materials are shared within the subject.** Every school admin and every teacher of the subject sees all its materials, drafts included, like the question bank. Approved materials feed AI questions for the whole subject.
3. **Versions never change.** A document belongs to one subject, has a title, description and topic tags (which can change), and one or more uploaded versions.
   - A version's file and its identity (name, kind, size, SHA-256, storage key, uploader) never change; the database refuses it. A corrected file or a new edition is a new version.
   - The text extracted from a version is stored in **segments** that record where they came from: a PDF page (with the chapter from the PDF's bookmarks), a Word section (with its heading), a PowerPoint slide (with its title), part of an Excel sheet (with its name and rows), rows of a CSV file, a range of lines in a text file, or a photo. Segments never change either, because AI citations point at them (ADR 0005).
   - Each version is reviewed on its own. The **newest approved version** is the one used as evidence; approving a new version replaces an older one, and an approved version stays approved when a newer one is uploaded but not yet reviewed.
4. **Review before use.** A version moves `queued → processing → extracted` (or `failed`, with a reason a teacher can act on), then `extracted → approved` or `rejected` (with a note).
   - Extraction reports **warnings** a reviewer must see: pages with no readable text (they may be scanned), a text file that wasn't UTF-8, a file with no text at all. Pages without readable text are kept as empty, flagged segments, so nothing on them is silently treated as read.
   - Approving a version with warnings needs the reviewer to confirm they've read them. A version with no readable text at all can't be approved.
   - Only approved versions of active documents will ever reach retrieval (Phase 4).
5. **Files are checked before anything is stored.**
   - The kind is decided from the content, not the name: PDF, Word (.docx), PowerPoint (.pptx), Excel (.xlsx), CSV, text, and JPEG or PNG photos. Unsupported, empty, older Office (.doc, .ppt, .xls), macro-enabled, template and password-protected files are refused with a message saying what to do instead.
   - Limits, configurable by environment: 25 MB per file, 1,000 PDF pages or slides, 200 MB unpacked for zip-based Office files (so a small file can't unpack into something huge), and 40 million pixels per photo. Excel files are parsed with `defusedxml`, which refuses XML bombs.
   - The same file can't be uploaded twice in a subject (compared by SHA-256).
   - Uploaded names are cleaned (no paths or control characters) and never used to decide where a file is stored; downloads are served as attachments with `nosniff`.
   - **Malware scanning is still open** (see below).
6. **Originals are kept behind a storage interface.** A directory on local disk (`STORAGE_DIR`) for now, so the API runs on a plain VPS; an S3-compatible adapter (AWS S3, Cloudflare R2, MinIO and others) comes before production hosting that lacks a persistent disk. Storage keys are made by the server from the school, document and version ids.
7. **Processing runs in the background, queued in the database.** The queue is the version's `status`. A worker claims a version with one conditional update, so two workers never take the same version, on SQLite or PostgreSQL, with no extra service such as Redis.
   - Production runs `python -m app.worker` beside the API (`DOCUMENT_PROCESSING=worker`).
   - Development and tests process each upload in the API process right after the response (`DOCUMENT_PROCESSING=inline`, the default).
   - A version left processing by a worker that stopped is retried after 15 minutes, up to three attempts, then marked failed. A failed version can be processed again on request.
8. **Libraries with permissive licences.** PDF text (and, for OCR, page images) comes from **pypdfium2** (Apache-2.0 / BSD-3), not PyMuPDF, whose AGPL licence would oblige the whole platform to be open-sourced or a commercial licence bought. Word comes from **python-docx**, PowerPoint from **python-pptx** and Excel from **openpyxl** (all MIT), pictures from **Pillow** (MIT-CMU), and CSV from Python's own `csv` module.
9. **OCR uses Tesseract on our own server** (stage C). It's free and open-source (Apache-2.0), keeps school documents off third-party services, and has no per-page cost. It's good on clear print and weak on handwriting and poor scans, so:
   - It reads PDF pages with no text layer (rendered at 300 DPI), uploaded JPEG and PNG photos (turned upright from their EXIF orientation), and PowerPoint slides that are only a picture.
   - Each OCR'd segment records `method = "ocr"` and a **confidence** (Tesseract's word confidences, averaged by length), and the version warns the reviewer to check OCR'd text against the file.
   - Below `OCR_MIN_CONFIDENCE` (60%) a segment is flagged `low_confidence`: the reviewer sees it, but it is **never used as AI evidence** (ADR 0005), so misread text can't become an exam question. A page OCR finds nothing on stays `no_text`.
   - Tesseract runs as a separate program, with one thread and a time limit per page, on a PNG we produce: it never parses the uploaded file. At most `OCR_MAX_PAGES` (200) scanned pages are read per file.
   - Without Tesseract installed, scanned pages stay flagged as before, with a warning saying OCR isn't set up, and photos are refused at upload. Production installs `tesseract-ocr` (and language packs for `OCR_LANGUAGES`, default English) beside the API and worker.
   - A cloud OCR service could be added later behind the same interface if schools need better results on poor scans or handwriting.
10. **Spreadsheets and presentations, as teachers use them.**
   - PowerPoint: one segment per slide, titled by the slide's title, with text in reading order (top to bottom, left to right), tables as rows, grouped shapes, and the **speaker notes**, which often hold the explanation.
   - Excel: each visible sheet's rows as "cell | cell" lines, with cached formula values; long sheets are split into parts of about 3,000 characters, each repeating the header row. **Hidden sheets are left out**, with a warning, because they often hold lookups or answers.
   - CSV: the separator is detected (comma, semicolon, tab or bar), and it's read as UTF-8 or, failing that, Windows text with a warning, like text files.
11. **Deleting is only for documents never approved.** Approved text may be cited by questions, so an approved document is archived instead (kept, but no longer used). Deleting removes the stored files too.

## Consequences

- Phase 4 can build retrieval chunks from the approved versions' segments, each already carrying its school, subject, document, version and location for citations.
- A school can always show where a question's evidence came from: the exact uploaded file (by SHA-256) and the page or section.
- Production needs a second process (the worker) and, until the S3 adapter exists, a persistent disk for `STORAGE_DIR`.
- Production should install Tesseract beside the API and worker; without it, scanned pages and photos can't be used.

## Still open

- Reading pictures inside Word files and on slides that also have text, and handwriting.
- **Malware scanning of uploads** (for example ClamAV beside the API). Type checking, size and unpacking limits and refusing macros reduce the risk, and files are never executed or served inline, but they don't replace a scanner.
- The S3-compatible storage adapter.
- Correcting extracted text by hand (rather than rejecting and uploading a better file).
- How long originals and extracted text are kept after a document is archived (retention).
