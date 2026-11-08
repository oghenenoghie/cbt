"""Running requests for drafts (ADR 0005, decision 5).

The queue is `ai_requests.status`, claimed with one conditional update exactly as uploads are
(`app/documents/processing.py`). Processing asks the provider for candidates from the request's
recorded sources, checks them (`app/ai/checks.py`), and stores every candidate: pending drafts
for those that passed, rejected ones with their reasons. It records the shortfall report and
what the provider calls cost. If the provider fails, the request is "failed" with a reason staff
can act on, and nothing is stored but the usage.

`python -m app.worker` runs this queue beside the uploads queue; in development and tests
(`AI_PROCESSING=inline`) a request is processed right after the response.
"""

import logging
from datetime import UTC, datetime, timedelta

from fastapi import BackgroundTasks
from sqlalchemy import select, update
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.orm import Session

from app.ai import checks
from app.ai.checks import SourceRef
from app.ai.provider import (
    CheckBrief,
    Provider,
    ProviderError,
    TopicChoice,
    Usage,
    WriteBrief,
    get_provider,
)
from app.ai.retrieval import location
from app.core.config import Settings, get_settings
from app.models import (
    AiRequest,
    AiSource,
    Document,
    DocumentSegment,
    DraftCitation,
    Question,
    QuestionDraft,
    QuestionVersion,
    Subject,
    Topic,
)

logger = logging.getLogger(__name__)

STUCK_AFTER = timedelta(minutes=30)
MAX_ATTEMPTS = 3
NOT_SET_UP = "AI drafting isn't set up on this server."
WENT_WRONG = "Something went wrong while drafting. Try again."


def now() -> datetime:
    return datetime.now(UTC)


def claim(db: Session, request_id: str) -> bool:
    result = db.execute(
        update(AiRequest)
        .where(AiRequest.id == request_id, AiRequest.status == "queued")
        .values(status="processing", processing_started_at=now(), attempts=AiRequest.attempts + 1)
    )
    db.commit()
    return result.rowcount == 1


def load_sources(db: Session, request: AiRequest) -> dict[str, SourceRef]:
    rows = db.execute(
        select(AiSource, DocumentSegment, Document)
        .join(DocumentSegment, DocumentSegment.id == AiSource.segment_id)
        .join(Document, Document.id == AiSource.document_id)
        .where(AiSource.request_id == request.id)
        .order_by(AiSource.position)
    ).all()
    return {
        source.label: SourceRef(
            label=source.label,
            segment_id=segment.id,
            text=segment.text,
            document=document.title,
            location=location(segment),
        )
        for source, segment, document in rows
    }


def existing_questions(db: Session, request: AiRequest) -> list[tuple[str, str]]:
    """Stems a new draft mustn't repeat: the subject's active bank questions and the pending
    drafts of its other requests."""
    bank = db.scalars(
        select(QuestionVersion.stem)
        .join(Question, Question.id == QuestionVersion.question_id)
        .where(
            Question.tenant_id == request.tenant_id,
            Question.subject_id == request.subject_id,
            Question.status == "active",
            QuestionVersion.version == Question.latest_version,
        )
    )
    pending = db.scalars(
        select(QuestionDraft.stem).where(
            QuestionDraft.tenant_id == request.tenant_id,
            QuestionDraft.subject_id == request.subject_id,
            QuestionDraft.status == "pending",
            QuestionDraft.request_id != request.id,
        )
    )
    return [(stem, "already in the bank") for stem in bank] + [
        (stem, "in a draft waiting for review") for stem in pending
    ]


def cost(usage: Usage, settings: Settings) -> float:
    return (
        usage.input_tokens * settings.ai_price_input
        + usage.output_tokens * settings.ai_price_output
        + usage.cache_read_tokens * settings.ai_price_cache_read
        + usage.cache_write_tokens * settings.ai_price_cache_write
    ) / 1_000_000


def _record_usage(request: AiRequest, usage: Usage, settings: Settings) -> None:
    request.model = usage.model or request.model
    request.provider_calls += usage.calls
    request.input_tokens += usage.input_tokens
    request.output_tokens += usage.output_tokens
    request.cache_read_tokens += usage.cache_read_tokens
    request.cache_write_tokens += usage.cache_write_tokens
    request.cost_usd += cost(usage, settings)
    request.latency_ms += round(usage.seconds * 1000)


def _fail(request: AiRequest, reason: str) -> None:
    request.status = "failed"
    request.error = reason
    request.finished_at = now()


def process_request(db: Session, request_id: str, provider: Provider | None = None) -> bool:
    """Draft questions for one queued request. False if it wasn't there to take."""
    if not claim(db, request_id):
        return False
    settings = get_settings()
    request = db.get(AiRequest, request_id)
    db.refresh(request)
    provider = provider or get_provider(settings)
    if provider is None:
        _fail(request, NOT_SET_UP)
        db.commit()
        return True

    subject = db.get(Subject, request.subject_id)
    topics = (
        db.scalars(
            select(Topic)
            .where(Topic.tenant_id == request.tenant_id, Topic.id.in_(request.topic_ids))
            .order_by(Topic.position, Topic.name)
        ).all()
        if request.topic_ids
        else []
    )
    choices = [TopicChoice(f"T{index}", t.name) for index, t in enumerate(topics, start=1)]
    topic_keys = {c.key: t.id for c, t in zip(choices, topics, strict=True)}
    sources = load_sources(db, request)

    usage = Usage()
    try:
        written = provider.write(
            WriteBrief(
                subject=subject.name,
                topics=choices,
                objective=request.objective,
                question_types=list(request.question_types),
                count=request.count,
                difficulty=request.difficulty,
                sources=[s.as_text() for s in sources.values()],
            )
        )
        usage.add(written.usage)
        reviewed = checks.screen(
            written.questions,
            count=request.count,
            question_types=list(request.question_types),
            marks=request.marks,
            difficulty=request.difficulty,
            sources=sources,
            topics=topic_keys,
            default_topic_ids=[topics[0].id] if len(topics) == 1 else [],
            existing=existing_questions(db, request),
        )
        items = checks.check_items(reviewed)
        if items and settings.ai_check_answers:
            checked = provider.check(
                CheckBrief(
                    subject=subject.name,
                    topics=[t.name for t in topics],
                    objective=request.objective,
                    items=items,
                    sources=checks.cited_sources(reviewed, sources),
                )
            )
            usage.add(checked.usage)
            checks.apply_verdicts(reviewed, checked)
        checks.remove_repeats(reviewed)
    except ProviderError as error:
        usage.add(error.usage)
        _record_usage(request, usage, settings)
        _fail(request, error.message)
        db.commit()
        return True
    except Exception:
        logger.exception("Drafting for AI request %s failed", request.id)
        db.rollback()
        request = db.get(AiRequest, request_id)
        _record_usage(request, usage, settings)
        _fail(request, WENT_WRONG)
        db.commit()
        return True

    for candidate in reviewed:
        draft = QuestionDraft(
            tenant_id=request.tenant_id,
            request_id=request.id,
            subject_id=request.subject_id,
            position=candidate.position,
            status="pending" if candidate.passed else "rejected",
            type=candidate.type,
            stem=candidate.stem,
            options=candidate.options,
            correct_option_ids=candidate.correct_option_ids,
            explanation=candidate.explanation,
            marks=candidate.marks,
            difficulty=candidate.difficulty,
            topic_ids=candidate.topic_ids,
            raw=candidate.raw,
            reasons=candidate.reasons,
            answer_check=(
                {
                    "supported": candidate.verdict.supported,
                    "single_answer": candidate.verdict.single_answer,
                    "clear": candidate.verdict.clear,
                    "in_scope": candidate.verdict.in_scope,
                    "assessment": candidate.verdict.assessment,
                }
                if candidate.verdict
                else None
            ),
        )
        db.add(draft)
        db.flush()
        for position, citation in enumerate(candidate.citations, start=1):
            db.add(
                DraftCitation(
                    tenant_id=request.tenant_id,
                    draft_id=draft.id,
                    position=position,
                    source_label=citation.label,
                    segment_id=citation.segment_id,
                    quote=citation.quote,
                    found=citation.found,
                )
            )

    accepted = sum(1 for c in reviewed if c.passed)
    rejected = len(reviewed) - accepted
    notes = list(request.notes or [])
    summary = f"Asked for {request.count}; {accepted} passed the checks and wait for review."
    if rejected:
        summary += f" {rejected} {'was' if rejected == 1 else 'were'} rejected, each with why."
    notes.insert(0, summary)
    if written.shortfall:
        notes.append(f"The AI said: {written.shortfall[:1000]}")
    if not settings.ai_check_answers:
        notes.append(
            "Answers weren't checked against the material automatically on this server; "
            "check each one when you review it."
        )
    request.notes = notes
    request.accepted_count = accepted
    request.rejected_count = rejected
    request.error = None
    request.status = "done"
    request.finished_at = now()
    _record_usage(request, usage, settings)
    db.commit()
    return True


def process_queued(db: Session, limit: int = 5) -> int:
    ids = db.scalars(
        select(AiRequest.id)
        .where(AiRequest.status == "queued")
        .order_by(AiRequest.created_at, AiRequest.id)
        .limit(limit)
    ).all()
    return sum(1 for request_id in ids if process_request(db, request_id))


def recover_stuck(db: Session) -> int:
    """Requeue requests left "processing" by a worker that stopped; give up after a few tries."""
    cutoff = now() - STUCK_AFTER
    stuck = (AiRequest.status == "processing", AiRequest.processing_started_at < cutoff)
    retried = db.execute(
        update(AiRequest).where(*stuck, AiRequest.attempts < MAX_ATTEMPTS).values(status="queued")
    ).rowcount
    db.execute(
        update(AiRequest)
        .where(*stuck, AiRequest.attempts >= MAX_ATTEMPTS)
        .values(status="failed", error=WENT_WRONG, finished_at=now())
    )
    db.commit()
    return retried


def _process_with_new_session(bind: Engine | Connection, request_id: str) -> None:
    with Session(bind=bind) as db:
        try:
            process_request(db, request_id)
        except Exception:  # the worker or a retry picks it up later
            logger.exception("Inline processing of AI request %s failed", request_id)


def process_soon(background: BackgroundTasks, db: Session, request_id: str) -> None:
    """Process a new or retried request right after the response, in inline mode."""
    if get_settings().ai_processing == "inline":
        background.add_task(_process_with_new_session, db.get_bind(), request_id)
