"""Choosing the evidence a request may use (ADR 0005, decision 3).

Only the newest approved version of each active document in the request's subject, in the
requester's school, is ever searched; a request can narrow that to some documents. Parts with no
readable text are left out, and so are parts read from a picture (OCR) with low confidence: the
reviewer saw them, but they may be misread, so they are never evidence. When the request names topics or a learning objective, the parts are
ranked by how well they match those words (BM25, the ranking classic search engines use) and
only parts that match are used; otherwise the documents are used in order. Either way the
evidence stops at a size limit, so a request's cost stays predictable.

This is lexical search: it finds parts that use the words of the topic and objective. It needs
no extra service and works the same on SQLite and PostgreSQL. Searching by meaning (embeddings)
can replace `rank` later without changing what is permitted.
"""

import math
from collections import Counter
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.text import terms
from app.models import Document, DocumentSegment, DocumentVersion

# A part shorter than this is a heading or a page number, not evidence.
MIN_SEGMENT_CHARS = 40
# BM25's usual settings.
K1 = 1.5
B = 0.75


@dataclass
class Evidence:
    segment: DocumentSegment
    document: Document
    version: DocumentVersion
    score: float = 0.0


@dataclass
class Retrieval:
    sources: list[Evidence]
    # Readable parts in scope, and parts left out because they had no readable text or were read
    # from a picture with low confidence.
    searched: int = 0
    unreadable: int = 0
    uncertain: int = 0
    # Parts that matched the search but didn't fit within the size limit.
    left_out: int = 0
    searched_for: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def location(segment: DocumentSegment) -> str:
    """Where a part is, in words a teacher would use: "page 12 (Chapter 3: Cells)"."""
    where = {
        "page": f"page {segment.number}",
        "section": f"section {segment.number}",
        "slide": f"slide {segment.number}",
        "sheet": f"sheet {segment.number}",
        "rows": f"from row {segment.number}",
        "lines": f"from line {segment.number}",
        "image": "the photo",
    }.get(segment.kind, f"part {segment.number}")
    if segment.kind == "rows":
        return where
    return f"{where} ({segment.label})" if segment.label else where


def approved_versions(
    db: Session, tenant_id: str, subject_id: str, document_ids: list[str] | None = None
) -> list[tuple[Document, DocumentVersion]]:
    """The newest approved version of each active document in the subject, by title."""
    query = select(Document).where(
        Document.tenant_id == tenant_id,
        Document.subject_id == subject_id,
        Document.status == "active",
    )
    if document_ids:
        query = query.where(Document.id.in_(document_ids))
    documents = {d.id: d for d in db.scalars(query)}
    if not documents:
        return []
    newest: dict[str, DocumentVersion] = {}
    for version in db.scalars(
        select(DocumentVersion)
        .where(
            DocumentVersion.tenant_id == tenant_id,
            DocumentVersion.document_id.in_(documents),
            DocumentVersion.status == "approved",
        )
        .order_by(DocumentVersion.version.desc())
    ):
        newest.setdefault(version.document_id, version)
    pairs = [(documents[doc_id], version) for doc_id, version in newest.items()]
    return sorted(pairs, key=lambda pair: (pair[0].title.casefold(), pair[0].id))


def readable(segment: DocumentSegment) -> bool:
    flags = segment.flags or []
    return (
        "no_text" not in flags
        and "low_confidence" not in flags
        and segment.char_count >= MIN_SEGMENT_CHARS
    )


def rank(texts: list[str], query: list[str]) -> list[float]:
    """BM25 score of each text for the query terms (0 when it has none of them)."""
    docs = [Counter(terms(t)) for t in texts]
    if not docs:
        return []
    lengths = [sum(d.values()) for d in docs]
    average = (sum(lengths) / len(lengths)) or 1.0
    wanted = set(query)
    frequency = Counter(term for d in docs for term in wanted if term in d)
    scores = []
    for doc, length in zip(docs, lengths, strict=True):
        score = 0.0
        for term in wanted:
            tf = doc.get(term, 0)
            if not tf:
                continue
            idf = math.log(1 + (len(docs) - frequency[term] + 0.5) / (frequency[term] + 0.5))
            score += idf * tf * (K1 + 1) / (tf + K1 * (1 - B + B * length / average))
        scores.append(score)
    return scores


def retrieve(
    db: Session,
    tenant_id: str,
    subject_id: str,
    *,
    document_ids: list[str] | None,
    search: list[str],
    max_sources: int,
    max_chars: int,
) -> Retrieval:
    """The evidence for a request: permitted, readable, matching, and within the limits."""
    versions = approved_versions(db, tenant_id, subject_id, document_ids)
    by_version = {version.id: (document, version) for document, version in versions}
    order = {version.id: index for index, (_, version) in enumerate(versions)}
    segments = (
        db.scalars(
            select(DocumentSegment).where(
                DocumentSegment.tenant_id == tenant_id,
                DocumentSegment.version_id.in_(by_version),
            )
        ).all()
        if by_version
        else []
    )
    segments = sorted(segments, key=lambda s: (order[s.version_id], s.position))
    usable = [s for s in segments if readable(s)]
    result = Retrieval(
        sources=[],
        searched=len(usable),
        unreadable=sum(1 for s in segments if "no_text" in (s.flags or [])),
        uncertain=sum(1 for s in segments if "low_confidence" in (s.flags or [])),
    )
    query = [t for phrase in search for t in terms(phrase)]
    result.searched_for = sorted(set(query))

    if query:
        scores = rank([s.text for s in usable], query)
        ranked = sorted(
            ((score, s) for score, s in zip(scores, usable, strict=True) if score > 0),
            key=lambda pair: (-pair[0], order[pair[1].version_id], pair[1].position),
        )
    else:
        ranked = [(0.0, s) for s in usable]

    chosen: list[tuple[float, DocumentSegment]] = []
    total = 0
    for score, segment in ranked:
        if len(chosen) >= max_sources or total + segment.char_count > max_chars:
            result.left_out += 1
            continue
        chosen.append((score, segment))
        total += segment.char_count
    # Give the model the parts in reading order, which reads better than best match first.
    chosen.sort(key=lambda pair: (order[pair[1].version_id], pair[1].position))
    result.sources = [
        Evidence(
            segment=s,
            document=by_version[s.version_id][0],
            version=by_version[s.version_id][1],
            score=score,
        )
        for score, s in chosen
    ]

    if result.unreadable:
        result.notes.append(
            f"{_parts(result.unreadable)} of the materials had no readable text and "
            f"{_were(result.unreadable)} used."
        )
    if result.uncertain:
        result.notes.append(
            f"{_parts(result.uncertain)} read from pictures with low confidence "
            f"{_were(result.uncertain)} used."
        )
    if result.left_out:
        what = "matched" if query else "were in scope"
        result.notes.append(
            f"{_parts(result.left_out)} more {what} but didn't fit in one request; "
            "narrow the request to use them."
        )
    return result


def _parts(n: int) -> str:
    return "1 part" if n == 1 else f"{n} parts"


def _were(n: int) -> str:
    return "wasn't" if n == 1 else "weren't"
