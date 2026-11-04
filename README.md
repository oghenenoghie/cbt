# Intelligent CBT Platform

An AI-powered Computer-Based Testing platform with two first-class clients:

- **Web application** for school administration, teachers, content management, examination authoring and online examinations.
- **Windows desktop application** for secure school-lab examinations, offline delivery and synchronization over a local network or the internet.

Both clients use shared backend services. AI-generated questions must be grounded exclusively in school-approved learning materials and must retain traceable source references.

## Product principles

1. **Source-grounded assessment:** no unsupported or general-knowledge question generation.
2. **Teacher approval:** AI-generated examinations remain drafts until reviewed and approved.
3. **Offline-first examinations:** students can sit assigned exams without an internet connection.
4. **Accuracy before automation:** diagrams, answer keys and marking rules require validation.
5. **Portable infrastructure:** avoid hard dependencies on a single hosting provider or AI vendor.
6. **Privacy and security:** isolate each school's data and protect exam content and student records.

## Planned architecture

| Area | Technology |
|---|---|
| Web | Next.js, React, TypeScript |
| Desktop | Electron, TypeScript |
| API | Python, FastAPI, Pydantic |
| Primary database | PostgreSQL |
| Desktop/local exam store | SQLite |
| Semantic retrieval | PostgreSQL + pgvector |
| Background jobs | Redis + Celery (introduced when needed) |
| Document processing | PyMuPDF, python-docx, python-pptx, OCR |
| Diagrams | SVG and deterministic rendering; image generation only where appropriate |
| Deployment | Docker; Railway/VPS-compatible backend and Vercel-compatible web app |

## Repository layout

```text
apps/
  web/                 Next.js web client
  desktop/             Electron Windows client
backend/
  api/                 FastAPI application
  ai-engine/           Source-grounded question generation
  document-engine/     Extraction, OCR and content indexing
  diagram-engine/      SVG, chart and diagram generation
  examination-engine/  Exam delivery, timing and grading
  workers/             Background processing
packages/
  shared-types/        Shared API/domain contracts
  ui/                  Shared web/desktop UI components
  sync/                Offline synchronization contracts
docs/
  architecture/        Architecture decision records and diagrams
  product/              Product requirements and workflows
infrastructure/
  docker/               Local development services
```

## Development status

This repository currently contains the initial product foundation and architecture. Feature implementation will proceed in small, verifiable increments.

See [Architecture](docs/architecture/overview.md) and [Product requirements](docs/product/requirements.md).

## Security

Never commit API keys, database credentials, student personal data, examination answer keys or production secrets. Use environment variables and untracked local environment files.
