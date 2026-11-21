"""The first public endpoints integrations call (ADR 0008, Integrations C).

Every endpoint here:
- authenticates the key and counts it against the integration's rate limit
  (`get_integration_principal`), then needs one permission (`require_scope`);
- reads and changes only the key's own school (`principal.tenant_id`);
- writes an audit entry with the integration as the actor, which its activity shows;
- answers errors in the public envelope (`EnvelopeRoute`).

What they do, as the user decided on 2026-11-21:
- `classes:read`: the school's sessions and terms, classes and subjects.
- `candidates:read`, `candidates:write`: students, identified by the integration's own IDs. A new
  student gets a student account **without a password**; a school admin sets one (or SSO, later),
  so passwords never pass through the other system. An existing student account with the same
  username is linked rather than duplicated. Integrations can enrol students and move them between
  classes in a session, but never disable an account or remove a student from a class: that stays
  with school admins.
- `results:read`: each student's score, total marks and percentage for exams whose results the
  school's release policy shows (released, or shown immediately). Never answers, questions or keys.
"""

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, Response, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.attempts import service as attempts
from app.core.audit import record_audit
from app.db.session import get_db
from app.integrations.auth import IntegrationPrincipal, get_integration_principal
from app.integrations.envelope import EnvelopeRoute, request_id_of
from app.integrations.public_schemas import (
    EXTERNAL_ID_PATTERN,
    AcademicSessionOut,
    CandidateClass,
    CandidateList,
    CandidateOut,
    CandidateResult,
    CandidateResults,
    CandidateSynced,
    CandidateUpsert,
    ClassOut,
    ExamResults,
    LevelOut,
    ReleasedExamList,
    ReleasedExamOut,
    StudentScore,
    SubjectOut,
    SubjectRef,
    TermOut,
)
from app.models import (
    AcademicSession,
    Candidate,
    CandidateExternalIdentity,
    ClassArm,
    ClassLevel,
    ClassLevelSubject,
    Enrolment,
    Exam,
    ExamArm,
    ExamAttempt,
    Subject,
    Term,
    User,
)
from app.models.identity import USERNAME_RULE, normalize_username, valid_username
from app.models.tenant import as_utc
from app.questions.common import newest_first
from app.results import service as results
from app.school.common import flush_or_conflict, invalid

router = APIRouter(tags=["integration API"], route_class=EnvelopeRoute)

CLASH = "That change clashed with another one at the same time. Try again."

ExternalId = Path(
    pattern=EXTERNAL_ID_PATTERN,
    description="The integration's own ID for the student: letters, digits and . _ : @ -",
)


def needs(scope: str):
    def dependency(
        principal: IntegrationPrincipal = Depends(get_integration_principal),
    ) -> IntegrationPrincipal:
        principal.require_scope(scope)
        return principal

    return dependency


classes_read = needs("classes:read")
candidates_read = needs("candidates:read")
candidates_write = needs("candidates:write")
results_read = needs("results:read")


def _audit(
    db: Session,
    principal: IntegrationPrincipal,
    request: Request,
    action: str,
    resource_type: str,
    resource_id: str | None = None,
    details: dict | None = None,
) -> None:
    entry = record_audit(
        db,
        tenant_id=principal.tenant_id,
        actor_type="integration",
        actor_id=principal.integration_id,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        request=request,
        details={"key_id": principal.credential_id, **(details or {})},
    )
    entry.request_id = request_id_of(request)


def _conflict(message: str) -> HTTPException:
    return HTTPException(status.HTTP_409_CONFLICT, detail=message)


def _current_session_id(db: Session, tenant_id: str) -> str | None:
    return db.scalar(
        select(AcademicSession.id).where(
            AcademicSession.tenant_id == tenant_id, AcademicSession.is_current.is_(True)
        )
    )


def _class_names(db: Session, arm_ids: set[str]) -> dict[str, CandidateClass]:
    if not arm_ids:
        return {}
    rows = db.execute(
        select(ClassArm.id, ClassArm.name, ClassArm.session_id, ClassLevel.name)
        .join(ClassLevel, ClassLevel.id == ClassArm.level_id)
        .where(ClassArm.id.in_(arm_ids))
    )
    return {
        arm_id: CandidateClass(id=arm_id, name=f"{level} {arm}", session_id=session_id)
        for arm_id, arm, session_id, level in rows
    }


# --- classes:read --------------------------------------------------------------------------------


@router.get("/academic-sessions", response_model=list[AcademicSessionOut])
def list_sessions(
    request: Request,
    principal: IntegrationPrincipal = Depends(classes_read),
    db: Session = Depends(get_db),
) -> list[AcademicSessionOut]:
    """The school's sessions, newest first, each with its terms."""
    sessions = list(
        db.scalars(
            select(AcademicSession)
            .where(AcademicSession.tenant_id == principal.tenant_id)
            .order_by(AcademicSession.starts_on.desc())
        )
    )
    terms: dict[str, list[TermOut]] = {s.id: [] for s in sessions}
    for term in db.scalars(
        select(Term).where(Term.tenant_id == principal.tenant_id).order_by(Term.position)
    ):
        terms.setdefault(term.session_id, []).append(
            TermOut(
                id=term.id,
                name=term.name,
                position=term.position,
                starts_on=term.starts_on,
                ends_on=term.ends_on,
            )
        )
    _audit(db, principal, request, "classes.read", "academic_session", details={"count": len(sessions)})
    db.commit()
    return [
        AcademicSessionOut(
            id=s.id,
            name=s.name,
            starts_on=s.starts_on,
            ends_on=s.ends_on,
            is_current=s.is_current,
            terms=terms[s.id],
        )
        for s in sessions
    ]


@router.get("/classes", response_model=list[ClassOut])
def list_classes(
    request: Request,
    session_id: str | None = Query(default=None, description="Defaults to the current session."),
    principal: IntegrationPrincipal = Depends(classes_read),
    db: Session = Depends(get_db),
) -> list[ClassOut]:
    """The classes (arms) of one session, by level, then name."""
    if session_id is None:
        session_id = _current_session_id(db, principal.tenant_id)
    elif db.scalar(
        select(AcademicSession.id).where(
            AcademicSession.id == session_id, AcademicSession.tenant_id == principal.tenant_id
        )
    ) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Session not found.")
    rows = (
        db.execute(
            select(ClassArm, ClassLevel)
            .join(ClassLevel, ClassLevel.id == ClassArm.level_id)
            .where(ClassArm.tenant_id == principal.tenant_id, ClassArm.session_id == session_id)
            .order_by(ClassLevel.position, ClassLevel.name, ClassArm.name)
        ).all()
        if session_id
        else []
    )
    _audit(db, principal, request, "classes.read", "class_arm", details={"count": len(rows)})
    db.commit()
    return [
        ClassOut(
            id=arm.id,
            name=f"{level.name} {arm.name}",
            level=LevelOut(id=level.id, name=level.name),
            arm=arm.name,
            session_id=arm.session_id,
        )
        for arm, level in rows
    ]


@router.get("/subjects", response_model=list[SubjectOut])
def list_subjects(
    request: Request,
    principal: IntegrationPrincipal = Depends(classes_read),
    db: Session = Depends(get_db),
) -> list[SubjectOut]:
    """The school's subjects, by name, with the class levels that take each."""
    subjects = list(
        db.scalars(
            select(Subject).where(Subject.tenant_id == principal.tenant_id).order_by(Subject.name)
        )
    )
    levels: dict[str, list[str]] = {s.id: [] for s in subjects}
    for subject_id, level_id in db.execute(
        select(ClassLevelSubject.subject_id, ClassLevelSubject.level_id).where(
            ClassLevelSubject.tenant_id == principal.tenant_id
        )
    ):
        levels.setdefault(subject_id, []).append(level_id)
    _audit(db, principal, request, "classes.read", "subject", details={"count": len(subjects)})
    db.commit()
    return [
        SubjectOut(id=s.id, name=s.name, code=s.code, level_ids=sorted(levels[s.id]))
        for s in subjects
    ]


# --- candidates ----------------------------------------------------------------------------------


def _external_ids(db: Session, principal: IntegrationPrincipal, candidate_ids: list[str]) -> dict:
    if not candidate_ids:
        return {}
    return dict(
        db.execute(
            select(CandidateExternalIdentity.candidate_id, CandidateExternalIdentity.external_id)
            .where(
                CandidateExternalIdentity.tenant_id == principal.tenant_id,
                CandidateExternalIdentity.external_system_id == principal.integration_id,
                CandidateExternalIdentity.candidate_id.in_(candidate_ids),
            )
        ).all()
    )


def _candidates_out(
    db: Session, principal: IntegrationPrincipal, candidates: list[Candidate]
) -> list[CandidateOut]:
    ids = [c.id for c in candidates]
    users = {
        u.id: u
        for u in db.scalars(
            select(User).where(User.id.in_({c.user_id for c in candidates if c.user_id}))
        )
    }
    external = _external_ids(db, principal, ids)
    current = _current_session_id(db, principal.tenant_id)
    arm_of = (
        dict(
            db.execute(
                select(Enrolment.candidate_id, Enrolment.arm_id).where(
                    Enrolment.session_id == current, Enrolment.candidate_id.in_(ids)
                )
            ).all()
        )
        if current and ids
        else {}
    )
    classes = _class_names(db, set(arm_of.values()))
    out = []
    for c in candidates:
        user = users.get(c.user_id)
        out.append(
            CandidateOut(
                id=c.id,
                external_id=external.get(c.id),
                display_name=c.display_name,
                username=user.username if user else None,
                account_status=user.status if user else None,
                has_password=bool(user and user.password_hash),
                current_class=classes.get(arm_of.get(c.id)),
            )
        )
    return out


def _by_external_id(db: Session, principal: IntegrationPrincipal, external_id: str) -> Candidate:
    candidate = db.scalar(
        select(Candidate)
        .join(
            CandidateExternalIdentity,
            CandidateExternalIdentity.candidate_id == Candidate.id,
        )
        .where(
            CandidateExternalIdentity.tenant_id == principal.tenant_id,
            CandidateExternalIdentity.external_system_id == principal.integration_id,
            CandidateExternalIdentity.external_id == external_id,
        )
    )
    if candidate is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="No student has that external ID.")
    return candidate


@router.get("/candidates", response_model=CandidateList)
def list_candidates(
    request: Request,
    after: str | None = Query(default=None, description="The `next_after` of the previous page."),
    limit: int = Query(default=100, ge=1, le=200),
    principal: IntegrationPrincipal = Depends(candidates_read),
    db: Session = Depends(get_db),
) -> CandidateList:
    """The school's students, newest first, with this integration's IDs for them."""
    query = select(Candidate).where(Candidate.tenant_id == principal.tenant_id)
    page, next_after = newest_first(db, principal, Candidate, query, after, limit)
    _audit(db, principal, request, "candidates.read", "candidate", details={"count": len(page)})
    db.commit()
    return CandidateList(candidates=_candidates_out(db, principal, page), next_after=next_after)


@router.get("/candidates/{external_id}", response_model=CandidateOut)
def get_candidate(
    request: Request,
    external_id: str = ExternalId,
    principal: IntegrationPrincipal = Depends(candidates_read),
    db: Session = Depends(get_db),
) -> CandidateOut:
    candidate = _by_external_id(db, principal, external_id)
    _audit(db, principal, request, "candidates.read", "candidate", candidate.id, {"count": 1})
    db.commit()
    return _candidates_out(db, principal, [candidate])[0]


def _account_for(
    db: Session, tenant_id: str, username: str, candidate: Candidate | None
) -> User | None:
    """The student account with this username, if there is one.

    For a `candidate` that has no account yet, the account must not belong to another student.
    """
    user = db.scalar(select(User).where(User.tenant_id == tenant_id, User.username == username))
    if user is None:
        return None
    if user.role != "student":
        raise _conflict("That username belongs to a staff account.")
    if candidate is not None:
        holder = db.scalar(select(Candidate.id).where(Candidate.user_id == user.id))
        if holder is not None and holder != candidate.id:
            raise _conflict("That username belongs to another student.")
    return user


@router.put("/candidates/{external_id}", response_model=CandidateSynced)
def sync_candidate(
    body: CandidateUpsert,
    request: Request,
    response: Response,
    external_id: str = ExternalId,
    principal: IntegrationPrincipal = Depends(candidates_write),
    db: Session = Depends(get_db),
) -> CandidateSynced:
    """Add or update a student by this integration's ID for them. Sending the same again changes
    nothing, so retries are safe.

    - A new ID with a username nobody has: a new student and a student account without a
      password (201). A school admin sets the password.
    - A new ID with an existing student's username: that student is linked to the ID.
    - A known ID: their name, username and class are brought up to date.
    - `class_id` enrols them in that class, or moves them to it from another class in its session.
    """
    tid = principal.tenant_id
    username = normalize_username(body.username)
    if not valid_username(username):
        raise invalid(USERNAME_RULE)

    changes: list[str] = []
    outcome = None
    identity = db.scalar(
        select(CandidateExternalIdentity).where(
            CandidateExternalIdentity.tenant_id == tid,
            CandidateExternalIdentity.external_system_id == principal.integration_id,
            CandidateExternalIdentity.external_id == external_id,
        )
    )
    if identity is not None:
        candidate = db.get(Candidate, identity.candidate_id)
        user = db.get(User, candidate.user_id) if candidate.user_id else None
        if user is not None and user.username != username:
            if db.scalar(select(User.id).where(User.tenant_id == tid, User.username == username)):
                raise _conflict("That username belongs to another account.")
            user.username = username
            changes.append("username")
        elif user is None:
            user = _account_for(db, tid, username, candidate)
            if user is None:
                user = User(tenant_id=tid, username=username, display_name=body.display_name, role="student")
                db.add(user)
                flush_or_conflict(db, CLASH)
            candidate.user_id = user.id
            changes.append("account")
    else:
        user = _account_for(db, tid, username, None)
        if user is None:
            user = User(tenant_id=tid, username=username, display_name=body.display_name, role="student")
            db.add(user)
            flush_or_conflict(db, CLASH)
            candidate = Candidate(tenant_id=tid, user_id=user.id, display_name=body.display_name)
            db.add(candidate)
            outcome = "created"
        else:
            candidate = db.scalar(select(Candidate).where(Candidate.user_id == user.id))
            if candidate is None:
                candidate = Candidate(tenant_id=tid, user_id=user.id, display_name=user.display_name)
                db.add(candidate)
            else:
                taken = db.scalar(
                    select(CandidateExternalIdentity.external_id).where(
                        CandidateExternalIdentity.candidate_id == candidate.id,
                        CandidateExternalIdentity.external_system_id == principal.integration_id,
                    )
                )
                if taken is not None:
                    raise _conflict(f"That student already has the external ID {taken}.")
            outcome = "linked"
        flush_or_conflict(db, CLASH)
        db.add(
            CandidateExternalIdentity(
                tenant_id=tid,
                candidate_id=candidate.id,
                external_system_id=principal.integration_id,
                external_id=external_id,
            )
        )

    if candidate.display_name != body.display_name or user.display_name != body.display_name:
        candidate.display_name = body.display_name
        user.display_name = body.display_name
        changes.append("display_name")

    class_change = None
    if body.class_id is not None:
        arm = db.scalar(select(ClassArm).where(ClassArm.id == body.class_id, ClassArm.tenant_id == tid))
        if arm is None:
            raise invalid("That class doesn't exist.")
        enrolment = db.scalar(
            select(Enrolment).where(
                Enrolment.candidate_id == candidate.id, Enrolment.session_id == arm.session_id
            )
        )
        if enrolment is None:
            db.add(
                Enrolment(
                    tenant_id=tid, session_id=arm.session_id, arm_id=arm.id, candidate_id=candidate.id
                )
            )
            class_change = "enrolled"
        elif enrolment.arm_id != arm.id:
            enrolment.arm_id = arm.id
            class_change = "moved"
        if class_change:
            changes.append(class_change)

    flush_or_conflict(db, CLASH)
    outcome = outcome or ("updated" if changes else "unchanged")
    details = {"external_id": external_id, "outcome": outcome, "changes": changes}
    if class_change:
        details["class"] = _class_names(db, {body.class_id})[body.class_id].name
    _audit(db, principal, request, f"candidate.{outcome}", "candidate", candidate.id, details)
    db.commit()
    response.status_code = status.HTTP_201_CREATED if outcome == "created" else status.HTTP_200_OK
    return CandidateSynced(outcome=outcome, candidate=_candidates_out(db, principal, [candidate])[0])


# --- results:read ------------------------------------------------------------------------------


def _released(tenant_id: str):
    """Published exams whose scores the school's release policy shows students now."""
    return select(Exam).where(
        Exam.tenant_id == tenant_id,
        Exam.status == "published",
        or_(Exam.results_release == "immediate", Exam.results_released_at.is_not(None)),
    )


def _exams_out(db: Session, exams: list[Exam]) -> dict[str, ReleasedExamOut]:
    ids = [e.id for e in exams]
    subjects = dict(
        db.execute(
            select(Subject.id, Subject.name).where(Subject.id.in_({e.subject_id for e in exams}))
        ).all()
    )
    arms: dict[str, list[str]] = {i: [] for i in ids}
    for exam_id, arm_id in db.execute(
        select(ExamArm.exam_id, ExamArm.arm_id).where(ExamArm.exam_id.in_(ids))
    ):
        arms[exam_id].append(arm_id)
    names = _class_names(db, {a for group in arms.values() for a in group})
    return {
        e.id: ReleasedExamOut(
            id=e.id,
            title=e.title,
            subject=SubjectRef(id=e.subject_id, name=subjects.get(e.subject_id, "")),
            term_id=e.term_id,
            classes=sorted((names[a] for a in arms[e.id]), key=lambda c: c.name),
            results_release=e.results_release,
            released_at=as_utc(e.results_released_at) if e.results_released_at else None,
            closes_at=as_utc(e.closes_at),
        )
        for e in exams
    }


def _finish_overdue(db: Session, query) -> None:
    if attempts.finish_overdue(db, list(db.scalars(query)), attempts.now()):
        db.commit()


@router.get("/released-results", response_model=ReleasedExamList)
def list_released(
    request: Request,
    after: str | None = Query(default=None, description="The `next_after` of the previous page."),
    limit: int = Query(default=50, ge=1, le=100),
    principal: IntegrationPrincipal = Depends(results_read),
    db: Session = Depends(get_db),
) -> ReleasedExamList:
    """Exams whose results students can see now, newest first."""
    page, next_after = newest_first(db, principal, Exam, _released(principal.tenant_id), after, limit)
    _audit(db, principal, request, "results.read", "exam", details={"count": len(page)})
    db.commit()
    out = _exams_out(db, page)
    return ReleasedExamList(exams=[out[e.id] for e in page], next_after=next_after)


@router.get("/released-results/{exam_id}", response_model=ExamResults)
def exam_results(
    exam_id: str,
    request: Request,
    principal: IntegrationPrincipal = Depends(results_read),
    db: Session = Depends(get_db),
) -> ExamResults:
    """Each student's score for one exam, by name. Students who didn't finish aren't listed."""
    exam = db.scalar(
        select(Exam).where(
            Exam.id == exam_id, Exam.tenant_id == principal.tenant_id, Exam.status == "published"
        )
    )
    if exam is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Exam not found.")
    if not results.score_visible(exam):
        raise _conflict("Results for this exam haven't been released yet.")
    _finish_overdue(
        db,
        select(ExamAttempt).where(
            ExamAttempt.exam_id == exam.id, ExamAttempt.status == "in_progress"
        ),
    )
    counted = [a for (e, _), a in results.counted_attempts(db, [exam.id]).items() if e == exam.id]
    totals = results.totals(db, counted)
    candidates = {
        c.id: c
        for c in db.scalars(select(Candidate).where(Candidate.id.in_({a.candidate_id for a in counted})))
    }
    usernames = dict(
        db.execute(
            select(User.id, User.username).where(
                User.id.in_({c.user_id for c in candidates.values() if c.user_id})
            )
        ).all()
    )
    external = _external_ids(db, principal, list(candidates))
    scores = sorted(
        (
            StudentScore(
                candidate_id=a.candidate_id,
                external_id=external.get(a.candidate_id),
                display_name=candidates[a.candidate_id].display_name,
                username=usernames.get(candidates[a.candidate_id].user_id),
                score=totals[a.id].score,
                max_score=a.max_score,
                percentage=results.percentage(totals[a.id].score, a.max_score),
                submitted_at=as_utc(a.submitted_at),
            )
            for a in counted
        ),
        key=lambda s: s.display_name.casefold(),
    )
    _audit(db, principal, request, "results.read", "exam", exam.id, {"count": len(scores)})
    db.commit()
    return ExamResults(exam=_exams_out(db, [exam])[exam.id], results=scores)


@router.get("/candidates/{external_id}/results", response_model=CandidateResults)
def candidate_results(
    request: Request,
    external_id: str = ExternalId,
    principal: IntegrationPrincipal = Depends(results_read),
    db: Session = Depends(get_db),
) -> CandidateResults:
    """One student's results that the school's release policy shows, latest exam first."""
    candidate = _by_external_id(db, principal, external_id)
    _finish_overdue(
        db,
        select(ExamAttempt).where(
            ExamAttempt.candidate_id == candidate.id, ExamAttempt.status == "in_progress"
        ),
    )
    sat = select(ExamAttempt.exam_id).where(
        ExamAttempt.candidate_id == candidate.id, ExamAttempt.status == "submitted"
    )
    exams = list(db.scalars(_released(principal.tenant_id).where(Exam.id.in_(sat))))
    counted = results.counted_attempts(db, [e.id for e in exams])
    mine = {e.id: counted[(e.id, candidate.id)] for e in exams if (e.id, candidate.id) in counted}
    totals = results.totals(db, list(mine.values()))
    described = _exams_out(db, exams)
    out = [
        CandidateResult(
            exam=described[e.id],
            score=totals[mine[e.id].id].score,
            max_score=mine[e.id].max_score,
            percentage=results.percentage(totals[mine[e.id].id].score, mine[e.id].max_score),
            submitted_at=as_utc(mine[e.id].submitted_at),
        )
        for e in sorted(exams, key=lambda e: as_utc(e.closes_at), reverse=True)
        if e.id in mine
    ]
    _audit(db, principal, request, "results.read", "candidate", candidate.id, {"count": len(out)})
    db.commit()
    return CandidateResults(candidate_id=candidate.id, external_id=external_id, results=out)
