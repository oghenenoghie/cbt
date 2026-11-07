# ADR 0002: School structure

- **Status:** Accepted
- **Date:** 2026-11-07
- **Implemented in:** `backend/api/app/models/academic.py`, `backend/api/app/school/` (migration `0004_school_structure`). Teacher assignment is still to come (Phase 2 part 5).

## Context

Phase 2 includes academic setup: "academic sessions; departments, classes, subjects and topics". Later phases build on it. Exams and results belong to a period of the school year. Students sit exams as members of a class. AI question generation is scoped to "a defined subject/topic scope", and teachers author and mark exams. The product docs didn't say how a school's year, classes and subjects are organised, so these were settled before building.

## Decisions

1. **The school year is an academic session split into terms.**
   - A session (e.g. "2026/2027") has start and end dates and ordered terms. A new session gets First, Second and Third Term by default, without dates. A school can define its own terms instead, one to six of them, for example two semesters.
   - Term dates are optional until the school sets them. When set, they must fall inside the session, and that's re-checked when the session's dates change.
   - At most one session per school is **current**. The database enforces this with a partial unique index.
   - Exams and results will belong to a term.
2. **Classes are levels with arms.**
   - Class levels (e.g. JSS1, SS2) carry over from year to year, ordered by position.
   - Each session has arms within a level (e.g. "JSS1 A"). Arm names are unique within a level and session, so "A" can exist again next year.
   - Students will be enrolled in an arm for a session (Phase 2 part 5).
3. **Each school keeps one subject list.**
   - A subject (e.g. Biology) has an optional short code, unique within the school, and ordered topics.
   - A subject is linked to the class levels that take it.
   - AI questions will be scoped to a subject and its topics.
4. **Teachers are assigned to arm + subject pairs** (e.g. JSS1 A Biology). They will create and mark exams only for their assignments. This comes in Phase 2 part 5.
5. **The database keeps every link inside one school.**
   - Composite foreign keys on `(id, tenant_id)` tie terms to sessions, arms to sessions and levels, topics to subjects, and level-subject links to both sides.
   - Children that only make sense with their parent are deleted with it: terms and arms with their session, and topics and level links with their subject.
   - A parent still in use can't be deleted. A class level with arms is refused, and so will be anything later records (exams, enrolments) point at.
6. **Who can do what.** Any signed-in member of the school can read the structure: admins, teachers and students. Only school admins can change it, and every change needs the CSRF token and writes an audit entry. Another school's records return 404.

## Consequences

- Deleting is refused (409, with an explanation) whenever something still points at the record. Mistakes are fixed by renaming or moving, not by forcing a delete.
- A session always keeps at least one term.
- Topics are ordered by `position`, then name. Positions are plain sort keys, not unique, so moving a topic is a single update.
- Departments, from the requirements list, aren't modelled yet. Add them when something needs them, such as reporting or access.

## Still open

- Whether students can see the whole school's structure, or only their own classes and subjects. This matters once enrolments exist.
- Promoting students to the next level at the end of a session: a bulk "roll over" action.
