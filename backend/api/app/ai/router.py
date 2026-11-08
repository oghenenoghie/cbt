"""AI question drafts (ADR 0005): `/api/v1/ai/requests` and `/api/v1/ai/drafts`.

The same people as the question bank use them: school admins, and teachers of the subject.
Students can't, because drafts carry answer keys. Making a request picks and records its
evidence straight away; drafting happens in the background. Staff then edit, approve (into the
bank, with citations) or dismiss each draft that passed the checks.
"""

from datetime import UTC, datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.ai.processing import process_soon
from app.ai.provider import drafting_enabled
from app.ai.retrieval import approved_versions, location, retrieve
from app.ai.schemas import (
    AiRequestCreate,
    AiRequestDetail,
    AiRequestList,
    AiRequestOut,
    CitationOut,
    DraftDismiss,
    DraftEdit,
    DraftList,
    DraftOut,
    SourceOut,
    UsageOut,
)
from app.ai.text import same_question
from app.auth.sessions import SessionPrincipal
from app.core.config import get_settings
from app.db.session import get_db
from app.models import (
    AiRequest,
    AiSource,
    Document,
    DocumentSegment,
    DocumentVersion,
    DraftCitation,
    Question,
    QuestionCitation,
    QuestionDraft,
    QuestionTopic,
    QuestionVersion,
    Subject,
    Topic,
    User,
)
from app.questions.common import (
    check_bank_access,
    newest_first,
    staff_read,
    staff_write,
    visible_subjects,
)
from app.questions.schemas import QuestionContent
from app.school.common import audit, flush_or_conflict, get_owned, invalid

router = APIRouter(prefix="/ai", tags=["AI question drafts"])

NOT_SET_UP = "AI drafting isn't set up on this server. Ask whoever runs the platform to turn it on."
NO_MATERIALS = (
    "There are no approved materials for this subject yet. Upload some and approve them first."
)
NOTHING_MATCHES = (
    "None of the approved materials mention these topics or this objective. Choose other "
    "topics, reword the objective, or pick the documents to use."
)


def _now() -> datetime:
    return datetime.now(UTC)


# Reading back ------------------------------------------------------------------------------


def _segments(db: Session, ids: set[str]) -> dict[str, tuple[DocumentSegment, Document, int]]:
    if not ids:
        return {}
    rows = db.execute(
        select(DocumentSegment, Document, DocumentVersion.version)
        .join(DocumentVersion, DocumentVersion.id == DocumentSegment.version_id)
        .join(Document, Document.id == DocumentVersion.document_id)
        .where(DocumentSegment.id.in_(ids))
    ).all()
    return {segment.id: (segment, document, number) for segment, document, number in rows}


def _drafts_out(db: Session, drafts: list[QuestionDraft]) -> list[DraftOut]:
    if not drafts:
        return []
    citations: dict[str, list[DraftCitation]] = {d.id: [] for d in drafts}
    for citation in db.scalars(
        select(DraftCitation)
        .where(DraftCitation.draft_id.in_(citations))
        .order_by(DraftCitation.position)
    ):
        citations[citation.draft_id].append(citation)
    segments = _segments(
        db, {c.segment_id for cs in citations.values() for c in cs if c.segment_id}
    )

    def citation_out(c: DraftCitation) -> CitationOut:
        segment, document, _ = segments.get(c.segment_id, (None, None, None))
        return CitationOut(
            position=c.position,
            source_label=c.source_label,
            segment_id=c.segment_id,
            document_id=document.id if document else None,
            document_title=document.title if document else None,
            location=location(segment) if segment else None,
            quote=c.quote,
            found=c.found,
        )

    return [
        DraftOut(
            id=d.id,
            request_id=d.request_id,
            subject_id=d.subject_id,
            position=d.position,
            status=d.status,
            type=d.type,
            stem=d.stem,
            options=d.options,
            correct_option_ids=d.correct_option_ids,
            explanation=d.explanation,
            marks=d.marks,
            difficulty=d.difficulty,
            topic_ids=d.topic_ids,
            reasons=d.reasons,
            answer_check=d.answer_check,
            citations=[citation_out(c) for c in citations[d.id]],
            edited_by_id=d.edited_by_id,
            edited_at=d.edited_at,
            reviewed_by_id=d.reviewed_by_id,
            reviewed_at=d.reviewed_at,
            review_note=d.review_note,
            question_id=d.question_id,
            created_at=d.created_at,
            updated_at=d.updated_at,
        )
        for d in drafts
    ]


def _requests_out(db: Session, requests: list[AiRequest]) -> list[AiRequestOut]:
    ids = {r.requested_by_id for r in requests if r.requested_by_id}
    names = (
        dict(db.execute(select(User.id, User.display_name).where(User.id.in_(ids))).all())
        if ids
        else {}
    )
    return [
        AiRequestOut(
            id=r.id,
            subject_id=r.subject_id,
            requested_by_id=r.requested_by_id,
            requested_by_name=names.get(r.requested_by_id),
            question_types=r.question_types,
            count=r.count,
            difficulty=r.difficulty,
            marks=r.marks,
            topic_ids=r.topic_ids,
            document_ids=r.document_ids,
            objective=r.objective,
            status=r.status,
            error=r.error,
            accepted_count=r.accepted_count,
            rejected_count=r.rejected_count,
            notes=r.notes,
            usage=UsageOut(
                model=r.model,
                provider_calls=r.provider_calls,
                input_tokens=r.input_tokens,
                output_tokens=r.output_tokens,
                cache_read_tokens=r.cache_read_tokens,
                cache_write_tokens=r.cache_write_tokens,
                cost_usd=round(r.cost_usd, 6),
                latency_ms=r.latency_ms,
            ),
            created_at=r.created_at,
            finished_at=r.finished_at,
        )
        for r in requests
    ]


def _detail(db: Session, request: AiRequest) -> AiRequestDetail:
    sources = db.scalars(
        select(AiSource).where(AiSource.request_id == request.id).order_by(AiSource.position)
    ).all()
    segments = _segments(db, {s.segment_id for s in sources})
    drafts = db.scalars(
        select(QuestionDraft)
        .where(QuestionDraft.request_id == request.id)
        .order_by(QuestionDraft.position)
    ).all()
    return AiRequestDetail(
        **_requests_out(db, [request])[0].model_dump(),
        sources=[
            SourceOut(
                label=s.label,
                segment_id=s.segment_id,
                document_id=s.document_id,
                document_title=segments[s.segment_id][1].title,
                version=segments[s.segment_id][2],
                location=location(segments[s.segment_id][0]),
                char_count=segments[s.segment_id][0].char_count,
                score=round(s.score, 4),
            )
            for s in sources
        ],
        drafts=_drafts_out(db, list(drafts)),
    )


def _request_for(db: Session, principal: SessionPrincipal, request_id: str) -> AiRequest:
    record = get_owned(db, AiRequest, request_id, principal, "Request")
    check_bank_access(db, principal, record.subject_id)
    return record


def _draft_for(db: Session, principal: SessionPrincipal, draft_id: str) -> QuestionDraft:
    draft = get_owned(db, QuestionDraft, draft_id, principal, "Draft")
    check_bank_access(db, principal, draft.subject_id)
    return draft


# Requests ----------------------------------------------------------------------------------


def _check_limits(db: Session, tenant_id: str, monthly: bool = True) -> None:
    """At most a few requests in progress per school, and a monthly allowance. A retry isn't a
    new request, so only the first limit applies to it."""
    settings = get_settings()
    open_requests = db.scalar(
        select(func.count())
        .select_from(AiRequest)
        .where(AiRequest.tenant_id == tenant_id, AiRequest.status.in_(("queued", "processing")))
    )
    if open_requests >= settings.ai_max_open_requests:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                f"Your school already has {open_requests} requests being drafted. "
                "Wait for one to finish, then try again."
            ),
        )
    if monthly and settings.ai_monthly_requests > 0:
        month_start = _now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        this_month = db.scalar(
            select(func.count())
            .select_from(AiRequest)
            .where(AiRequest.tenant_id == tenant_id, AiRequest.created_at >= month_start)
        )
        if this_month >= settings.ai_monthly_requests:
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                detail=(
                    f"Your school has used this month's {settings.ai_monthly_requests} "
                    "requests for AI drafts. The limit resets on the 1st."
                ),
            )


def _check_documents(
    db: Session, principal: SessionPrincipal, subject_id: str, document_ids: list[str]
) -> None:
    documents = {
        d.id: d
        for d in db.scalars(
            select(Document).where(
                Document.tenant_id == principal.tenant_id, Document.id.in_(document_ids)
            )
        )
    }
    for document_id in document_ids:
        document = documents.get(document_id)
        if document is None or document.subject_id != subject_id:
            raise invalid("Choose documents from this subject's materials.")
        if document.status != "active":
            raise invalid(f"“{document.title}” is archived. Restore it to use it.")
    approved = {
        d.id for d, _ in approved_versions(db, principal.tenant_id, subject_id, document_ids)
    }
    for document_id in document_ids:
        if document_id not in approved:
            raise invalid(f"“{documents[document_id].title}” has no approved version yet.")


@router.post("/requests", response_model=AiRequestDetail, status_code=status.HTTP_202_ACCEPTED)
def create_request(
    body: AiRequestCreate,
    request: Request,
    background: BackgroundTasks,
    principal: SessionPrincipal = Depends(staff_write),
    db: Session = Depends(get_db),
) -> AiRequestDetail:
    """Ask for drafts. The evidence is chosen and recorded now; drafting follows in the
    background, so poll the request until it is "done" or "failed"."""
    settings = get_settings()
    if not drafting_enabled(settings):
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail=NOT_SET_UP)
    subject = db.scalar(
        select(Subject).where(
            Subject.id == body.subject_id, Subject.tenant_id == principal.tenant_id
        )
    )
    if subject is None:
        raise invalid("That subject doesn't exist.")
    check_bank_access(db, principal, subject.id)
    if body.count > settings.ai_max_questions:
        raise invalid(f"Ask for at most {settings.ai_max_questions} questions at a time.")
    topics = (
        db.scalars(
            select(Topic).where(
                Topic.tenant_id == principal.tenant_id,
                Topic.subject_id == subject.id,
                Topic.id.in_(body.topic_ids),
            )
        ).all()
        if body.topic_ids
        else []
    )
    if len(topics) != len(body.topic_ids):
        raise invalid("Topics must belong to the subject.")
    if body.document_ids:
        _check_documents(db, principal, subject.id, body.document_ids)
    _check_limits(db, principal.tenant_id)

    search = [t.name for t in topics] + ([body.objective] if body.objective else [])
    found = retrieve(
        db,
        principal.tenant_id,
        subject.id,
        document_ids=body.document_ids or None,
        search=search,
        max_sources=settings.ai_max_sources,
        max_chars=settings.ai_max_source_chars,
    )
    if not found.sources:
        if not approved_versions(db, principal.tenant_id, subject.id, body.document_ids or None):
            raise invalid(NO_MATERIALS)
        raise invalid(NOTHING_MATCHES if search else NO_MATERIALS)

    documents = {e.document.id for e in found.sources}
    notes = [
        f"Used {len(found.sources)} of {found.searched} readable parts, from "
        f"{len(documents)} document{'s' if len(documents) != 1 else ''}."
    ] + found.notes
    record = AiRequest(
        tenant_id=principal.tenant_id,
        subject_id=subject.id,
        requested_by_id=principal.user_id,
        question_types=body.question_types,
        count=body.count,
        difficulty=body.difficulty,
        marks=body.marks,
        topic_ids=body.topic_ids,
        document_ids=body.document_ids,
        objective=body.objective,
        notes=notes,
    )
    db.add(record)
    db.flush()
    for position, evidence in enumerate(found.sources, start=1):
        db.add(
            AiSource(
                tenant_id=principal.tenant_id,
                request_id=record.id,
                label=f"S{position}",
                position=position,
                segment_id=evidence.segment.id,
                version_id=evidence.version.id,
                document_id=evidence.document.id,
                score=evidence.score,
            )
        )
    audit(
        db,
        principal,
        request,
        "ai_request.created",
        "ai_request",
        record.id,
        {"subject": subject.name, "count": body.count, "sources": len(found.sources)},
    )
    db.commit()
    process_soon(background, db, record.id)
    return _detail(db, record)


@router.get("/requests", response_model=AiRequestList)
def list_requests(
    subject_id: str | None = None,
    request_status: str | None = Query(
        default=None, alias="status", pattern="^(queued|processing|done|failed)$"
    ),
    after: str | None = Query(default=None, description="The `next_after` of the previous page."),
    limit: int = Query(default=50, ge=1, le=200),
    principal: SessionPrincipal = Depends(staff_read),
    db: Session = Depends(get_db),
) -> AiRequestList:
    """Requests, newest first. Teachers see the subjects they teach."""
    query = select(AiRequest).where(AiRequest.tenant_id == principal.tenant_id)
    query = visible_subjects(db, principal, AiRequest, query, subject_id)
    if request_status is not None:
        query = query.where(AiRequest.status == request_status)
    page, next_after = newest_first(db, principal, AiRequest, query, after, limit)
    return AiRequestList(requests=_requests_out(db, page), next_after=next_after)


@router.get("/requests/{request_id}", response_model=AiRequestDetail)
def get_request(
    request_id: str,
    principal: SessionPrincipal = Depends(staff_read),
    db: Session = Depends(get_db),
) -> AiRequestDetail:
    return _detail(db, _request_for(db, principal, request_id))


@router.post("/requests/{request_id}/retry", response_model=AiRequestDetail)
def retry_request(
    request_id: str,
    request: Request,
    background: BackgroundTasks,
    principal: SessionPrincipal = Depends(staff_write),
    db: Session = Depends(get_db),
) -> AiRequestDetail:
    """Draft a failed request again, from the same evidence."""
    record = _request_for(db, principal, request_id)
    if record.status != "failed":
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail="Only a failed request can be retried."
        )
    if not drafting_enabled():
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail=NOT_SET_UP)
    _check_limits(db, principal.tenant_id, monthly=False)
    record.status = "queued"
    record.error = None
    record.finished_at = None
    audit(db, principal, request, "ai_request.retried", "ai_request", record.id)
    db.commit()
    process_soon(background, db, record.id)
    return _detail(db, record)


# Drafts ------------------------------------------------------------------------------------


@router.get("/drafts", response_model=DraftList)
def list_drafts(
    subject_id: str | None = None,
    request_id: str | None = None,
    draft_status: str = Query(
        default="pending", alias="status", pattern="^(pending|approved|dismissed|rejected)$"
    ),
    after: str | None = Query(default=None, description="The `next_after` of the previous page."),
    limit: int = Query(default=50, ge=1, le=200),
    principal: SessionPrincipal = Depends(staff_read),
    db: Session = Depends(get_db),
) -> DraftList:
    """Drafts waiting for review (or with another status), newest first."""
    query = select(QuestionDraft).where(
        QuestionDraft.tenant_id == principal.tenant_id, QuestionDraft.status == draft_status
    )
    query = visible_subjects(db, principal, QuestionDraft, query, subject_id)
    if request_id is not None:
        query = query.where(QuestionDraft.request_id == request_id)
    page, next_after = newest_first(db, principal, QuestionDraft, query, after, limit)
    return DraftList(drafts=_drafts_out(db, page), next_after=next_after)


@router.get("/drafts/{draft_id}", response_model=DraftOut)
def get_draft(
    draft_id: str,
    principal: SessionPrincipal = Depends(staff_read),
    db: Session = Depends(get_db),
) -> DraftOut:
    return _drafts_out(db, [_draft_for(db, principal, draft_id)])[0]


def _require_pending(draft: QuestionDraft) -> None:
    if draft.status == "rejected":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="This draft failed the checks, so it can't be used. Write it in the bank instead.",
        )
    if draft.status != "pending":
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail=f"This draft was already {draft.status}."
        )


def _subject_topics(
    db: Session, tenant_id: str, subject_id: str, topic_ids: list[str]
) -> list[str]:
    """The ones of `topic_ids` that are (still) topics of the subject, in the order given."""
    if not topic_ids:
        return []
    found = set(
        db.scalars(
            select(Topic.id).where(
                Topic.tenant_id == tenant_id,
                Topic.subject_id == subject_id,
                Topic.id.in_(topic_ids),
            )
        )
    )
    return [t for t in dict.fromkeys(topic_ids) if t in found]


def _content(draft: QuestionDraft) -> QuestionContent:
    if draft.type == "true_false":
        correct: bool | int = draft.correct_option_ids == ["true"]
        options = None
    else:
        ids = [o["id"] for o in draft.options]
        correct = ids.index(draft.correct_option_ids[0])
        options = [o["text"] for o in draft.options]
    return QuestionContent(
        type=draft.type,
        stem=draft.stem,
        options=options,
        correct=correct,
        explanation=draft.explanation,
        marks=draft.marks,
        difficulty=draft.difficulty,
    )


@router.patch("/drafts/{draft_id}", response_model=DraftOut)
def edit_draft(
    draft_id: str,
    body: DraftEdit,
    request: Request,
    principal: SessionPrincipal = Depends(staff_write),
    db: Session = Depends(get_db),
) -> DraftOut:
    """Correct a pending draft's wording, answer or topics before approving it."""
    draft = _draft_for(db, principal, draft_id)
    _require_pending(draft)
    if body.content is not None:
        options, correct = body.content.to_storage()
        draft.type = body.content.type
        draft.stem = body.content.stem
        draft.options = options
        draft.correct_option_ids = correct
        draft.explanation = body.content.explanation
        draft.marks = body.content.marks
        draft.difficulty = body.content.difficulty
    if body.topic_ids is not None:
        kept = _subject_topics(db, principal.tenant_id, draft.subject_id, body.topic_ids)
        if len(kept) != len(set(body.topic_ids)):
            raise invalid("Topics must belong to the draft's subject.")
        draft.topic_ids = kept
    draft.edited_by_id = principal.user_id
    draft.edited_at = _now()
    audit(db, principal, request, "ai_draft.edited", "ai_draft", draft.id)
    db.commit()
    return _drafts_out(db, [draft])[0]


@router.post("/drafts/{draft_id}/approve", response_model=DraftOut)
def approve_draft(
    draft_id: str,
    request: Request,
    principal: SessionPrincipal = Depends(staff_write),
    db: Session = Depends(get_db),
) -> DraftOut:
    """Add a pending draft to the question bank, keeping its verified citations."""
    draft = _draft_for(db, principal, draft_id)
    _require_pending(draft)
    content = _content(draft)
    citations = db.scalars(
        select(DraftCitation)
        .where(DraftCitation.draft_id == draft.id, DraftCitation.found.is_(True))
        .order_by(DraftCitation.position)
    ).all()
    if not citations:
        raise invalid("This draft has no verified citation, so it can't be approved.")
    bank = db.scalars(
        select(QuestionVersion.stem)
        .join(Question, Question.id == QuestionVersion.question_id)
        .where(
            Question.tenant_id == principal.tenant_id,
            Question.subject_id == draft.subject_id,
            Question.status == "active",
            QuestionVersion.version == Question.latest_version,
        )
    )
    repeat = next((stem for stem in bank if same_question(content.stem, stem)), None)
    if repeat is not None:
        raise invalid(
            f"A question very like this is already in the bank: “{repeat[:200]}”. "
            "Edit the draft or dismiss it."
        )

    # Claim the draft, so two people approving at once can't both add it.
    claimed = db.execute(
        update(QuestionDraft)
        .where(QuestionDraft.id == draft.id, QuestionDraft.status == "pending")
        .values(status="approved", reviewed_by_id=principal.user_id, reviewed_at=_now())
    ).rowcount
    if claimed != 1:
        db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail="Someone else just reviewed this draft."
        )

    topic_ids = _subject_topics(db, principal.tenant_id, draft.subject_id, draft.topic_ids)
    question = Question(
        tenant_id=principal.tenant_id,
        subject_id=draft.subject_id,
        source="ai",
        created_by_id=principal.user_id,
        latest_version=1,
    )
    db.add(question)
    db.flush()
    options, correct = content.to_storage()
    version = QuestionVersion(
        tenant_id=principal.tenant_id,
        question_id=question.id,
        version=1,
        type=content.type,
        stem=content.stem,
        options=options,
        correct_option_ids=correct,
        explanation=content.explanation,
        marks=content.marks,
        difficulty=content.difficulty,
        created_by_id=principal.user_id,
    )
    db.add(version)
    db.flush()
    for topic_id in topic_ids:
        db.add(
            QuestionTopic(tenant_id=principal.tenant_id, question_id=question.id, topic_id=topic_id)
        )
    for position, citation in enumerate(citations, start=1):
        db.add(
            QuestionCitation(
                tenant_id=principal.tenant_id,
                question_version_id=version.id,
                position=position,
                segment_id=citation.segment_id,
                quote=citation.quote,
            )
        )
    db.execute(
        update(QuestionDraft).where(QuestionDraft.id == draft.id).values(question_id=question.id)
    )
    flush_or_conflict(db, "That draft clashed with another change. Try again.")
    subject = db.get(Subject, draft.subject_id)
    audit(
        db,
        principal,
        request,
        "question.created",
        "question",
        question.id,
        {"subject": subject.name, "type": content.type, "source": "ai", "draft": draft.id},
    )
    audit(
        db, principal, request, "ai_draft.approved", "ai_draft", draft.id, {"question": question.id}
    )
    db.commit()
    db.refresh(draft)
    return _drafts_out(db, [draft])[0]


@router.post("/drafts/{draft_id}/dismiss", response_model=DraftOut)
def dismiss_draft(
    draft_id: str,
    body: DraftDismiss,
    request: Request,
    principal: SessionPrincipal = Depends(staff_write),
    db: Session = Depends(get_db),
) -> DraftOut:
    """Turn a pending draft down. It stays on its request's record."""
    draft = _draft_for(db, principal, draft_id)
    _require_pending(draft)
    note = (body.note or "").strip() or None
    claimed = db.execute(
        update(QuestionDraft)
        .where(QuestionDraft.id == draft.id, QuestionDraft.status == "pending")
        .values(
            status="dismissed",
            reviewed_by_id=principal.user_id,
            reviewed_at=_now(),
            review_note=note,
        )
    ).rowcount
    if claimed != 1:
        db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail="Someone else just reviewed this draft."
        )
    audit(db, principal, request, "ai_draft.dismissed", "ai_draft", draft.id)
    db.commit()
    db.refresh(draft)
    return _drafts_out(db, [draft])[0]
