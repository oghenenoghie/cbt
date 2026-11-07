"""Academic sessions and their terms (ADR 0002)."""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.auth.sessions import SessionPrincipal
from app.db.session import get_db
from app.models import AcademicSession, Term
from app.school.common import (
    audit,
    flush_or_conflict,
    get_owned,
    invalid,
    read_access,
    write_access,
)
from app.school.schemas import (
    SessionCreate,
    SessionOut,
    SessionUpdate,
    TermIn,
    TermOut,
    TermUpdate,
)

router = APIRouter(prefix="/school", tags=["school calendar"])

DEFAULT_TERMS = ("First Term", "Second Term", "Third Term")
SESSION_NAME_TAKEN = "A session with that name already exists."
TERM_NAME_TAKEN = "This session already has a term with that name."


def _terms_of(db: Session, session_ids: list[str]) -> dict[str, list[Term]]:
    by_session: dict[str, list[Term]] = {sid: [] for sid in session_ids}
    if session_ids:
        for term in db.scalars(
            select(Term).where(Term.session_id.in_(session_ids)).order_by(Term.position)
        ):
            by_session[term.session_id].append(term)
    return by_session


def _out(session: AcademicSession, terms: list[Term]) -> SessionOut:
    return SessionOut(
        id=session.id,
        name=session.name,
        starts_on=session.starts_on,
        ends_on=session.ends_on,
        is_current=session.is_current,
        terms=[
            TermOut(
                id=t.id, name=t.name, position=t.position, starts_on=t.starts_on, ends_on=t.ends_on
            )
            for t in terms
        ],
    )


def _session_out(db: Session, session: AcademicSession) -> SessionOut:
    return _out(session, _terms_of(db, [session.id])[session.id])


def _check_term_dates(
    session: AcademicSession, name: str, starts_on: date | None, ends_on: date | None
) -> None:
    if starts_on is not None and ends_on is not None and ends_on <= starts_on:
        raise invalid(f"{name} must end after it starts.")
    for day in (starts_on, ends_on):
        if day is not None and not session.starts_on <= day <= session.ends_on:
            raise invalid(
                f"{name} must fall within the session ({session.starts_on} to {session.ends_on})."
            )


@router.get("/sessions", response_model=list[SessionOut])
def list_sessions(
    principal: SessionPrincipal = Depends(read_access), db: Session = Depends(get_db)
) -> list[SessionOut]:
    """The school's sessions, newest first, each with its terms in order."""
    sessions = db.scalars(
        select(AcademicSession)
        .where(AcademicSession.tenant_id == principal.tenant_id)
        .order_by(AcademicSession.starts_on.desc())
    ).all()
    terms = _terms_of(db, [s.id for s in sessions])
    return [_out(s, terms[s.id]) for s in sessions]


@router.post("/sessions", response_model=SessionOut, status_code=status.HTTP_201_CREATED)
def create_session(
    body: SessionCreate,
    request: Request,
    principal: SessionPrincipal = Depends(write_access),
    db: Session = Depends(get_db),
) -> SessionOut:
    """Create a session. Without `terms`, it gets First, Second and Third Term (no dates yet)."""
    session = AcademicSession(
        tenant_id=principal.tenant_id,
        name=body.name,
        starts_on=body.starts_on,
        ends_on=body.ends_on,
    )
    term_inputs = body.terms or [TermIn(name=name) for name in DEFAULT_TERMS]
    for term in term_inputs:
        _check_term_dates(session, term.name, term.starts_on, term.ends_on)
    db.add(session)
    flush_or_conflict(db, SESSION_NAME_TAKEN)
    for position, term in enumerate(term_inputs, start=1):
        db.add(
            Term(
                tenant_id=principal.tenant_id,
                session_id=session.id,
                name=term.name,
                position=position,
                starts_on=term.starts_on,
                ends_on=term.ends_on,
            )
        )
    flush_or_conflict(db, TERM_NAME_TAKEN)
    audit(
        db,
        principal,
        request,
        "academic_session.created",
        "academic_session",
        session.id,
        {"name": session.name, "terms": len(term_inputs)},
    )
    db.commit()
    return _session_out(db, session)


@router.patch("/sessions/{session_id}", response_model=SessionOut)
def update_session(
    session_id: str,
    body: SessionUpdate,
    request: Request,
    principal: SessionPrincipal = Depends(write_access),
    db: Session = Depends(get_db),
) -> SessionOut:
    session = get_owned(db, AcademicSession, session_id, principal, "Session")
    changes = body.model_dump(exclude_unset=True)
    if any(changes.get(field, "set") is None for field in ("name", "starts_on", "ends_on")):
        raise invalid("A session's name and dates can't be empty.")
    changed = sorted(f for f, v in changes.items() if getattr(session, f) != v)
    for field in changed:
        setattr(session, field, changes[field])
    if session.ends_on <= session.starts_on:
        raise invalid("A session must end after it starts.")
    for term in _terms_of(db, [session.id])[session.id]:
        _check_term_dates(session, term.name, term.starts_on, term.ends_on)

    flush_or_conflict(db, SESSION_NAME_TAKEN)
    if changed:
        audit(
            db,
            principal,
            request,
            "academic_session.updated",
            "academic_session",
            session.id,
            {"fields": changed},
        )
    db.commit()
    return _session_out(db, session)


@router.post("/sessions/{session_id}/make-current", response_model=SessionOut)
def make_current(
    session_id: str,
    request: Request,
    principal: SessionPrincipal = Depends(write_access),
    db: Session = Depends(get_db),
) -> SessionOut:
    """Mark this session as the school's current one (any other stops being current)."""
    session = get_owned(db, AcademicSession, session_id, principal, "Session")
    if not session.is_current:
        # Clear the old one first: the database allows only one current session per school.
        db.execute(
            update(AcademicSession)
            .where(AcademicSession.tenant_id == principal.tenant_id, AcademicSession.is_current)
            .values(is_current=False)
        )
        session.is_current = True
        flush_or_conflict(db, "Another session became current at the same time. Try again.")
        audit(
            db, principal, request, "academic_session.made_current", "academic_session", session.id
        )
        db.commit()
    db.refresh(session)
    return _session_out(db, session)


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_session(
    session_id: str,
    request: Request,
    principal: SessionPrincipal = Depends(write_access),
    db: Session = Depends(get_db),
) -> Response:
    """Delete a session with its terms and class arms. Refused once anything else uses them."""
    session = get_owned(db, AcademicSession, session_id, principal, "Session")
    db.delete(session)
    flush_or_conflict(db, "This session is still in use, so it can't be deleted.")
    audit(
        db,
        principal,
        request,
        "academic_session.deleted",
        "academic_session",
        session_id,
        {"name": session.name},
    )
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/sessions/{session_id}/terms", response_model=TermOut, status_code=status.HTTP_201_CREATED
)
def add_term(
    session_id: str,
    body: TermIn,
    request: Request,
    principal: SessionPrincipal = Depends(write_access),
    db: Session = Depends(get_db),
) -> TermOut:
    """Add a term after the session's existing terms."""
    session = get_owned(db, AcademicSession, session_id, principal, "Session")
    _check_term_dates(session, body.name, body.starts_on, body.ends_on)
    last = db.scalar(select(func.max(Term.position)).where(Term.session_id == session.id)) or 0
    term = Term(
        tenant_id=principal.tenant_id,
        session_id=session.id,
        name=body.name,
        position=last + 1,
        starts_on=body.starts_on,
        ends_on=body.ends_on,
    )
    db.add(term)
    flush_or_conflict(db, TERM_NAME_TAKEN)
    audit(db, principal, request, "term.created", "term", term.id, {"name": term.name})
    db.commit()
    return TermOut(
        id=term.id,
        name=term.name,
        position=term.position,
        starts_on=term.starts_on,
        ends_on=term.ends_on,
    )


@router.patch("/terms/{term_id}", response_model=TermOut)
def update_term(
    term_id: str,
    body: TermUpdate,
    request: Request,
    principal: SessionPrincipal = Depends(write_access),
    db: Session = Depends(get_db),
) -> TermOut:
    term = get_owned(db, Term, term_id, principal, "Term")
    changes = body.model_dump(exclude_unset=True)
    if "name" in changes and changes["name"] is None:
        raise invalid("A term's name can't be empty.")
    changed = sorted(f for f, v in changes.items() if getattr(term, f) != v)
    for field in changed:
        setattr(term, field, changes[field])
    session = db.get(AcademicSession, term.session_id)
    _check_term_dates(session, term.name, term.starts_on, term.ends_on)

    flush_or_conflict(db, TERM_NAME_TAKEN)
    if changed:
        audit(db, principal, request, "term.updated", "term", term.id, {"fields": changed})
    db.commit()
    return TermOut(
        id=term.id,
        name=term.name,
        position=term.position,
        starts_on=term.starts_on,
        ends_on=term.ends_on,
    )


@router.delete("/terms/{term_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_term(
    term_id: str,
    request: Request,
    principal: SessionPrincipal = Depends(write_access),
    db: Session = Depends(get_db),
) -> Response:
    term = get_owned(db, Term, term_id, principal, "Term")
    remaining = db.scalar(
        select(func.count()).select_from(Term).where(Term.session_id == term.session_id)
    )
    if remaining <= 1:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="A session needs at least one term.")
    db.delete(term)
    flush_or_conflict(db, "This term is still in use, so it can't be deleted.")
    audit(db, principal, request, "term.deleted", "term", term_id, {"name": term.name})
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
