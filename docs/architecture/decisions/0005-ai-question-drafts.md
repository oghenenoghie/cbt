# ADR 0005: AI question drafts from approved materials

- **Status:** Accepted. Stages A and B are built.
- **Date:** 2026-11-08
- **Implemented in:** `backend/api/app/models/ai.py`, `backend/api/app/ai/`, `backend/api/app/worker.py` (migration `0012_ai_drafts`)

## Context

Schools can upload learning materials and approve their extracted text (ADR 0004, stage A). Phase 4 is the product's point: exam questions drafted by AI **only** from a school's approved materials, with citations, checked by the server and approved by a teacher before they reach the question bank.

The product docs fix the rules (`docs/architecture/overview.md` §2, `backend/ai-engine/README.md`, the acceptance rule in `docs/product/requirements.md`):

- evidence comes only from the requesting school's approved document versions, never from the internet or the model's general knowledge;
- each candidate carries citations; the server validates schema, citation coverage, answer support, scope and duplication, and model output never bypasses that;
- the response gives accepted drafts, rejected candidates with reasons, and an evidence-shortfall report, never padding the count with weak questions;
- drafts stay drafts until a teacher approves them, and drafts are kept apart from the bank's immutable versions;
- the model provider sits behind a replaceable adapter;
- AI cost and latency are observable.

They didn't fix the provider, how retrieval works, or who reviews drafts. When Phase 4 began, the user asked to move on without further questions, so the choices below follow the recommendations already made in this project (and the pattern of ADR 0004). Each can be changed.

The work is built in stages:

- **A. Requests, evidence, drafting, checks and review**, through the API. (Built.)
- **B. Web screens** for asking, reviewing drafts beside their evidence, and approving. (Built: `apps/web`, `/drafting`.)

PowerPoint, Excel, CSV and OCR (ADR 0004 stages B and C) are still to come. Until they exist, only PDF pages with text, Word and text files can be evidence.

## Decisions

1. **Subject staff ask, review and approve.** The same people as the question bank and the materials (`can_use_question_bank`): school admins, and teachers who teach the subject. They can approve drafts they asked for: the teacher's review is the approval the acceptance rule requires, and exam approval (ADR 0003) still follows separately. Requests and drafts are shared within the subject. Students can't reach any of it, because drafts carry answer keys.

2. **Claude, through the Anthropic API, behind a provider interface.** `app/ai/provider.py` defines the interface: `write` (candidate questions from numbered sources) and `check` (verdicts on candidates against the sources they cite). `AI_PROVIDER` picks the implementation:
   - `anthropic`: Claude (`app/ai/claude.py`, the official `anthropic` SDK). The model is configurable (`AI_MODEL`, default `claude-opus-5-5`), as are the effort level and token limits. Each call is one streamed request whose answer is constrained to a JSON schema (structured outputs). If the model's safeguards decline a request, the API's server-side fallback retries on a suitable model (`AI_FALLBACKS`), and the model that answered is recorded.
   - `fake`: deterministic, mechanical questions from sentences in the sources, so the flow and the web screens can be tried without a key or any cost. Tests script it.
   - `off` (the default): drafting is unavailable (503), so nothing is spent until someone sets it up.
   - The API key comes from the environment (`ANTHROPIC_API_KEY`, read by the SDK). It is never stored in the database or sent to a client.
   - What is sent: the subject's name, topic names, the request's objective and the chosen extracts of approved materials. Never student data.

3. **Lexical retrieval, chosen and recorded when the request is made.** Only the newest approved version of each active document in the subject, in the requester's school, is searched; a request can narrow it to some documents. Parts flagged as having no readable text, or too short to be evidence, are left out. When the request names topics or an objective, parts are ranked by BM25 on those words and only parts that match are used; otherwise documents are used in order. The evidence stops at a size limit (`AI_MAX_SOURCES`, `AI_MAX_SOURCE_CHARS`), so a request's cost is predictable.
   - The chosen parts are stored as the request's sources (`AiSource`, labelled S1, S2, ...), which never change. They are the record of exactly what the model was given, and a retry uses the same ones.
   - If nothing permitted matches, the request is refused straight away (422) with what to change, and nothing is spent.
   - Why lexical, when the overview planned pgvector: a request searches one school's materials for one subject, which is small; BM25 needs no embedding provider and no extension, behaves the same on SQLite (tests) and PostgreSQL, and is easy to explain. Searching by meaning (embeddings, pgvector) can replace the ranking later without changing what is permitted.

4. **Nothing the model writes is trusted.** The server checks every candidate (`app/ai/checks.py`):
   - **format:** it must fit the bank's format (`QuestionContent`) as one of the requested types; multiple choice needs at least three options and no "all/none of the above"; marks come from the request, not the model;
   - **citations:** at least one quote must be found, word for word (ignoring punctuation, case, spacing and typographic variants, and allowing "..." between parts of at least three words), in a source the request was given; quotes shorter than three words don't count. A source the model invents is never found;
   - **duplication:** it mustn't repeat an active bank question in the subject, a pending draft from another request, or an earlier candidate in the same request;
   - **count:** questions beyond the number asked for are rejected;
   - **answer support, single answer, clarity and scope:** a second model pass (the answer check) sees each remaining candidate with only its found quotes and the sources they come from, and says whether those establish the marked answer, whether only one option is right, whether it's clear and whether it's on the requested topics or objective. A missing verdict rejects the candidate. `AI_CHECK_ANSWERS=false` turns the pass off, and the report then says answers weren't checked.
   - A candidate that fails is stored as **rejected**, with every reason in words a teacher understands, and can't be approved or edited. One that passes becomes a **pending** draft.

5. **Drafting runs in the background, queued in the database**, exactly like uploads (ADR 0004, decision 7): `ai_requests.status` is the queue, claimed by one conditional update. `python -m app.worker` processes it in production (`AI_PROCESSING=worker`); development and tests draft right after the response (`inline`). A request left processing for 30 minutes is retried, up to three attempts. A provider failure (busy, refused, cut short, unreadable) marks the request failed with a message staff can act on and stores no drafts; staff can retry it.

6. **Every request has a shortfall report.** Its `notes` say how many were asked for and how many passed, how much of the materials was used, parts with no readable text, parts that matched but didn't fit, what the model said was missing, and whether answers were checked. Rejected candidates carry their own reasons.

7. **Review: edit, approve or dismiss.** Staff can edit a pending draft's wording, answer, marks and topics; the citations stay as they were checked, and the draft records who edited it. **Approving** adds a question to the bank with `source = "ai"`, whose first version keeps the draft's found citations (`QuestionCitation`, pointing at the document segment and never changing; `GET /questions/{id}/citations`). Approval is refused when the draft has no found citation or the bank already holds a question very like it. Two people approving at once can't both add it. **Dismissing** keeps the draft on the request's record with an optional note.

8. **Limits and cost.** At most 20 questions per request (`AI_MAX_QUESTIONS`), three requests in progress per school (`AI_MAX_OPEN_REQUESTS`) and 200 requests per school per month (`AI_MONTHLY_REQUESTS`; a retry doesn't count as a new one). Each request records the model that answered, calls, input, output and cache tokens, the time spent waiting for the provider, and an estimated cost from configurable prices (`AI_PRICE_*`, US dollars per million tokens).

9. **Question types: what the bank has.** Single-answer multiple choice and true/false. The bank now holds more types (ADR 0006); drafting them, with checks that suit them, is ADR 0006's stage C.

10. **The material is data, not instructions.** Sources are sent inside `<source>` tags that the material can't close, and both prompts tell the model to ignore instructions inside them. The checks above don't depend on the model obeying that.

## Consequences

- Every AI question in the bank can show the exact passage of approved material, its page or section and the document version it came from.
- Teachers only ever review candidates that already quote the material and passed the answer check; the rest are visible with reasons, so the shortfall is honest.
- A deployment needs an Anthropic API key (and, in production, the worker) to draft; without one, everything else works and drafting says it isn't set up.
- Costs are bounded per request and per school, and visible on every request.

## Still open

- **Per-school consent to sending materials to the AI provider**, and how long the provider may keep them. For now the platform operator turns drafting on for everyone by setting `AI_PROVIDER`.
- Retrieval by meaning (embeddings with pgvector) alongside BM25, if lexical matching proves too narrow.
- Whether an approved citation should warn when its document is archived or a newer version is approved.
- Reports of AI usage and cost across a school (per request is recorded now).
- More question types, and diagram-based questions (Phase 6).
