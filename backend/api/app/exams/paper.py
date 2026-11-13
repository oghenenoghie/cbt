"""Building an exam's paper (ADR 0003).

A draft's paper is worked out from the bank's latest versions, so it can change until the exam is
submitted. Submitting stores it as `ExamPaperItem` rows pinned to exact versions; from then on
the paper is read back from those rows and never changes.
"""

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import (
    Exam,
    ExamItem,
    ExamPaperItem,
    Passage,
    PassageVersion,
    Question,
    QuestionVersion,
)


@dataclass
class PaperEntry:
    question_id: str
    version: QuestionVersion
    marks: int


@dataclass
class Block:
    """An item of the exam: one question, or a passage with its questions. Kept together."""

    number: int
    passage_id: str | None = None
    passage: PassageVersion | None = None
    questions: list[PaperEntry] = field(default_factory=list)


def _latest_question_versions(db: Session, ids: list[str]) -> dict[str, QuestionVersion]:
    if not ids:
        return {}
    rows = db.scalars(
        select(QuestionVersion)
        .join(Question, Question.id == QuestionVersion.question_id)
        .where(
            QuestionVersion.question_id.in_(ids), QuestionVersion.version == Question.latest_version
        )
    )
    return {v.question_id: v for v in rows}


def _latest_passage_versions(db: Session, ids: list[str]) -> dict[str, PassageVersion]:
    if not ids:
        return {}
    rows = db.scalars(
        select(PassageVersion)
        .join(Passage, Passage.id == PassageVersion.passage_id)
        .where(PassageVersion.passage_id.in_(ids), PassageVersion.version == Passage.latest_version)
    )
    return {v.passage_id: v for v in rows}


def draft_paper(db: Session, exam: Exam) -> tuple[list[Block], list[str]]:
    """The paper as it would be frozen now, and anything that stops it being submitted."""
    items = db.scalars(
        select(ExamItem).where(ExamItem.exam_id == exam.id).order_by(ExamItem.position)
    ).all()
    question_ids = [i.question_id for i in items if i.question_id]
    passage_ids = [i.passage_id for i in items if i.passage_id]
    questions = {q.id: q for q in db.scalars(select(Question).where(Question.id.in_(question_ids)))}
    passages = {p.id: p for p in db.scalars(select(Passage).where(Passage.id.in_(passage_ids)))}
    following: dict[str, list[str]] = {pid: [] for pid in passage_ids}
    for passage_id, question_id in db.execute(
        select(Question.passage_id, Question.id)
        .where(Question.passage_id.in_(passage_ids), Question.status == "active")
        .order_by(Question.created_at, Question.id)
    ):
        following[passage_id].append(question_id)

    versions = _latest_question_versions(
        db, question_ids + [qid for qids in following.values() for qid in qids]
    )
    passage_versions = _latest_passage_versions(db, passage_ids)

    blocks: list[Block] = []
    problems: list[str] = []
    for number, item in enumerate(items, start=1):
        block = Block(number=number)
        if item.question_id is not None:
            if questions[item.question_id].status != "active":
                problems.append(f"Item {number}: the question has been archived.")
            version = versions[item.question_id]
            block.questions.append(PaperEntry(item.question_id, version, version.marks))
        else:
            if passages[item.passage_id].status != "active":
                problems.append(f"Item {number}: the passage has been archived.")
            if not following[item.passage_id]:
                problems.append(f"Item {number}: the passage has no active questions.")
            block.passage_id = item.passage_id
            block.passage = passage_versions[item.passage_id]
            for question_id in following[item.passage_id]:
                version = versions[question_id]
                block.questions.append(PaperEntry(question_id, version, version.marks))
        blocks.append(block)
    if not blocks:
        problems.append("Add at least one question or passage.")
    if exam.results_release == "immediate" and any(
        entry.version.type == "essay" for block in blocks for entry in block.questions
    ):
        problems.append(
            "Written answers are marked by a teacher, so set “Results” to “When a teacher "
            "releases them”."
        )
    return blocks, problems


def frozen_paper(db: Session, exam: Exam) -> list[Block]:
    """The paper stored when the exam was submitted."""
    rows = db.execute(
        select(ExamPaperItem, QuestionVersion, PassageVersion)
        .join(QuestionVersion, QuestionVersion.id == ExamPaperItem.question_version_id)
        .outerjoin(PassageVersion, PassageVersion.id == ExamPaperItem.passage_version_id)
        .where(ExamPaperItem.exam_id == exam.id)
        .order_by(ExamPaperItem.position)
    ).all()
    blocks: list[Block] = []
    for item, version, passage in rows:
        if not blocks or blocks[-1].number != item.block:
            blocks.append(
                Block(
                    number=item.block,
                    passage_id=passage.passage_id if passage else None,
                    passage=passage,
                )
            )
        blocks[-1].questions.append(PaperEntry(version.question_id, version, item.marks))
    return blocks


def paper_rows(exam: Exam, blocks: list[Block]) -> list[ExamPaperItem]:
    """The rows that freeze `blocks` as the exam's paper."""
    rows = []
    position = 0
    for block in blocks:
        for entry in block.questions:
            position += 1
            rows.append(
                ExamPaperItem(
                    tenant_id=exam.tenant_id,
                    exam_id=exam.id,
                    position=position,
                    block=block.number,
                    question_version_id=entry.version.id,
                    passage_version_id=block.passage.id if block.passage else None,
                    marks=entry.marks,
                )
            )
    return rows
