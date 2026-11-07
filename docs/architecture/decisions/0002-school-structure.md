# ADR 0002: School structure

- **Status:** Accepted
- **Date:** 2026-11-07
- **Implemented in:**
  - structure: `backend/api/app/models/academic.py`, `backend/api/app/school/` (migration `0004_school_structure`)
  - people in classes: `backend/api/app/models/classroom.py`, `backend/api/app/school/enrolments.py`, `assignments.py`, `me.py`, `access.py` (migration `0005_classrooms`)

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
   - Students are enrolled in an arm for a session (decision 7).
3. **Each school keeps one subject list.**
   - A subject (e.g. Biology) has an optional short code, unique within the school, and ordered topics.
   - A subject is linked to the class levels that take it.
   - AI questions will be scoped to a subject and its topics.
4. **Teachers are assigned to arm + subject pairs** (e.g. JSS1 A Biology).
   - Staff accounts can be assigned (teachers, and school admins who also teach), and the arm's level must take the subject.
   - Exam and marking endpoints must call `require_teaching` (`app/school/access.py`), which allows school admins and teachers assigned to that arm and subject.
   - A teacher sees the class list of an arm they teach any subject to. Their own assignments are at `GET /api/v1/me/classes`.
5. **The database keeps every link inside one school.**
   - Composite foreign keys on `(id, tenant_id)` tie terms to sessions, arms to sessions and levels, topics to subjects, and level-subject links to both sides.
   - Children that only make sense with their parent are deleted with it: terms and arms with their session, and topics and level links with their subject.
   - A parent still in use can't be deleted. A class level with arms is refused, and so is an arm with enrolled students (and therefore its session). Exams will get the same protection.
6. **Who can do what.**
   - Staff (school admins and teachers) can read the school structure. Only school admins can change it, and every change needs the CSRF token and writes an audit entry.
   - **Students see only their own classes:** their arm in each session and that level's subjects, at `GET /api/v1/me/classes`. They can't list the whole school's structure. This follows the product rule of minimising student-facing data.
   - Another school's records return 404.
7. **Enrolment rules.**
   - Enrolling a student account creates and links its candidate record if it has none. Only student accounts can be linked (ADR 0001).
   - A candidate is in **one arm per session**. The database enforces this: an enrolment references its arm by `(id, session_id, tenant_id)`, so its session is always the arm's session, and `(session_id, candidate_id)` is unique.
   - Bulk enrolment of up to 200 students is all-or-nothing, with errors listed by row.
   - Moving a student is only allowed to another arm in the same session. Next session is a new enrolment.

## Consequences

- Deleting is refused (409, with an explanation) whenever something still points at the record. Mistakes are fixed by renaming or moving, not by forcing a delete.
- A session always keeps at least one term.
- Topics are ordered by `position`, then name. Positions are plain sort keys, not unique, so moving a topic is a single update.
- Departments, from the requirements list, aren't modelled yet. Add them when something needs them, such as reporting or access.

## Still open

- Enrolling candidates who have no student account (for example ones provisioned by an SIS integration) waits for integration candidate provisioning.
- Promoting students to the next level at the end of a session: a bulk "roll over" action.
