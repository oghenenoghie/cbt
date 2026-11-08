# ADR 0004: Learning materials

- **Status:** Accepted. Stages A and D are built; stages B and C follow.
- **Date:** 2026-11-08
- **Implemented in:** `backend/api/app/models/documents.py`, `backend/api/app/documents/`, `backend/api/app/core/storage.py`, `backend/api/app/worker.py` (migration `0011_documents`)

## Context

The exam workflow is complete (ADR 0003). The product's next step, and its point, is questions drafted by AI from a school's own materials, never from the model's general knowledge (Phase 4). That needs the materials first: uploaded, read reliably, with every piece of text traceable to where it came from, and checked by a person before anything relies on it.

The product docs fix the inputs (PDF, scanned PDF, Word, PowerPoint, Excel, CSV, text, JPG and PNG), the processing stages (validate, store immutably, extract with page, slide and sheet provenance, OCR scans, report confidence and errors, publish to retrieval only after approval) and one hard rule: never treat failed or low-quality OCR as complete content. They didn't say who uploads and approves, which OCR to use, or who sees what. Those were settled with the user before building.

The work is built in stages, each its own change:

- **A. Upload, storage, extraction and review** for PDF (with a text layer), Word (.docx) and plain text, through the API. (Built.)
- **B. PowerPoint, Excel and CSV**, with slide and sheet provenance.
- **C. Scanned pages and images (OCR)**, with a confidence for each page.
- **D. Web screens** for uploading, reviewing and approving. (Built: `apps/web`, `/materials`.)

## Decisions

1. **Subject staff upload and approve, including their own uploads.**
   - School admins, and teachers who teach the subject to any class, can upload a subject's materials and approve them: the same people who can use its question bank (ADR 0003, decision 5).
   - Approving means "the extracted text is faithful to the file", not "this is good teaching material", so approving your own upload is allowed. (Exams are different: nobody approves an exam they prepared.)
   - Students can't reach materials at all.
2. **Materials are shared within the subject.** Every school admin and every teacher of the subject sees all its materials, drafts included, like the question bank. Approved materials feed AI questions for the whole subject.
3. **Versions never change.** A document belongs to one subject, has a title, description and topic tags (which can change), and one or more uploaded versions.
   - A version's file and its identity (name, kind, size, SHA-256, storage key, uploader) never change; the database refuses it. A corrected file or a new edition is a new version.
   - The text extracted from a version is stored in **segments** that record where they came from: a PDF page (with the chapter from the PDF's bookmarks), a Word section (with its heading) or a range of lines in a text file. Segments never change either, because Phase 4 citations will point at them.
   - Each version is reviewed on its own. The **newest approved version** is the one used as evidence; approving a new version replaces an older one, and an approved version stays approved when a newer one is uploaded but not yet reviewed.
4. **Review before use.** A version moves `queued → processing → extracted` (or `failed`, with a reason a teacher can act on), then `extracted → approved` or `rejected` (with a note).
   - Extraction reports **warnings** a reviewer must see: pages with no readable text (they may be scanned), a text file that wasn't UTF-8, a file with no text at all. Pages without readable text are kept as empty, flagged segments, so nothing on them is silently treated as read.
   - Approving a version with warnings needs the reviewer to confirm they've read them. A version with no readable text at all can't be approved.
   - Only approved versions of active documents will ever reach retrieval (Phase 4).
5. **Files are checked before anything is stored.**
   - The kind is decided from the content, not the name. Unsupported, empty, older Word (.doc), macro-enabled Office and password-protected files are refused with a message saying what to do instead.
   - Limits, configurable by environment: 25 MB per file, 1,000 PDF pages, and 200 MB unpacked for zip-based Office files (so a small file can't unpack into something huge).
   - The same file can't be uploaded twice in a subject (compared by SHA-256).
   - Uploaded names are cleaned (no paths or control characters) and never used to decide where a file is stored; downloads are served as attachments with `nosniff`.
   - **Malware scanning is still open** (see below).
6. **Originals are kept behind a storage interface.** A directory on local disk (`STORAGE_DIR`) for now, so the API runs on a plain VPS; an S3-compatible adapter (AWS S3, Cloudflare R2, MinIO and others) comes before production hosting that lacks a persistent disk. Storage keys are made by the server from the school, document and version ids.
7. **Processing runs in the background, queued in the database.** The queue is the version's `status`. A worker claims a version with one conditional update, so two workers never take the same version, on SQLite or PostgreSQL, with no extra service such as Redis.
   - Production runs `python -m app.worker` beside the API (`DOCUMENT_PROCESSING=worker`).
   - Development and tests process each upload in the API process right after the response (`DOCUMENT_PROCESSING=inline`, the default).
   - A version left processing by a worker that stopped is retried after 15 minutes, up to three attempts, then marked failed. A failed version can be processed again on request.
8. **Libraries with permissive licences.** PDF text (and, for OCR, page images) comes from **pypdfium2** (Apache-2.0 / BSD-3), not PyMuPDF, whose AGPL licence would oblige the whole platform to be open-sourced or a commercial licence bought. Word comes from **python-docx** (MIT).
9. **OCR will use Tesseract on our own server** (stage C). It's free and open-source, keeps school documents off third-party services, and has no per-page cost. It's good on clear print and weak on handwriting and poor scans, so each OCR'd page will carry a confidence, and low-confidence pages will be flagged for the reviewer like pages with no text. A cloud OCR service could be added later behind the same interface if schools need better results on poor scans.
10. **Deleting is only for documents never approved.** Approved text may be cited by questions, so an approved document is archived instead (kept, but no longer used). Deleting removes the stored files too.

## Consequences

- Phase 4 can build retrieval chunks from the approved versions' segments, each already carrying its school, subject, document, version and location for citations.
- A school can always show where a question's evidence came from: the exact uploaded file (by SHA-256) and the page or section.
- Production needs a second process (the worker) and, until the S3 adapter exists, a persistent disk for `STORAGE_DIR`.

## Still open

- **Malware scanning of uploads** (for example ClamAV beside the API). Type checking, size and unpacking limits and refusing macros reduce the risk, and files are never executed or served inline, but they don't replace a scanner.
- The S3-compatible storage adapter.
- Correcting extracted text by hand (rather than rejecting and uploading a better file).
- How long originals and extracted text are kept after a document is archived (retention).
