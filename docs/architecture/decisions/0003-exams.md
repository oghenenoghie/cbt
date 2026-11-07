# ADR 0003: Exams and the question bank

- **Status:** Accepted (the question bank is built; exams follow in stages)
- **Date:** 2026-11-07
- **Implemented in:**
  - question bank: `backend/api/app/models/questions.py`, `backend/api/app/questions/` (migration `0006_question_bank`)

## Context

With the school foundation in place (ADRs 0001 and 0002), the next product step is a basic exam workflow, built before documents and AI so the AI work has a question bank and exams to feed. The product docs list the parts (question bank, exam builder, exam delivery, grading, results) and the integrity rules (immutable published snapshots, append-only answer events, no answer keys or early results for candidates). They didn't say who publishes, how results are released, how many attempts students get, or whether order is shuffled. Those were settled before building.

The work is built in four stages, each its own change:

- **A. Question bank:** single-answer multiple-choice and true/false questions, versioned. (Built.)
- **B. Exam builder and publishing:** a teacher prepares an exam for arm + subject pairs and submits it; a school admin approves and publishes it, freezing a snapshot.
- **C. Sitting an exam:** start and resume, a server-side timer, append-only answer events, submission and auto-grading.
- **D. Results:** release, students' own results, and item analysis.

## Decisions

1. **Results are released by the teacher.**
   - Scores stay hidden from students until the exam's teacher (or a school admin) releases them.
   - A teacher can choose "show results immediately" for an exam instead, for example for a practice test.
   - Candidate-facing endpoints check this before returning anything about a result.
2. **Publishing needs a school admin's approval.**
   - A teacher prepares an exam and submits it. A school admin approves and publishes it, or sends it back with a note.
   - Publishing freezes an **immutable snapshot**: the exact question versions, their order, marks and settings. Later edits to the bank or the exam template never change a published exam.
   - The teacher can only prepare exams for arm + subject pairs they're assigned to (`require_teaching`, ADR 0002).
3. **One timed attempt by default.**
   - An exam has an availability window and a duration. A student gets one attempt. The teacher can allow more.
   - An attempt can be resumed (after a crash or a lost connection), but the clock keeps running from when it started. The server owns the clock; the client's timer is only a display.
   - When time runs out, the attempt is submitted with the answers saved so far.
4. **Question and option order are shuffled per student by default.**
   - Each attempt gets its own order, chosen once at the start and kept on resume. Teachers can turn shuffling off for an exam.
   - True/false options are never shuffled.
5. **The question bank is shared per subject.**
   - School admins, and teachers who teach the subject to any arm, can read and edit the subject's questions, whoever wrote them. Students can't reach the bank at all, because it holds answer keys.
   - A teacher who stops teaching a subject loses access to its questions. The questions stay.
   - Another school's questions return 404. A subject the caller doesn't teach returns 403.
6. **Questions are versioned, and versions never change.**
   - A question holds its subject, topic tags and status. Its content (stem, options, answer key, explanation, marks, difficulty) lives in **versions**. Editing adds version n+1; earlier versions are kept exactly as they were, and `QuestionVersion` refuses ORM updates.
   - A published exam will point at specific versions, so a question can be improved for future exams without touching past ones.
   - Two simultaneous edits can't both become version n+1: the unique `(question_id, version)` constraint makes the second a 409.
   - Topic tags and status aren't content, so changing them doesn't add a version.
7. **Question types so far: `mcq_single` and `true_false`.**
   - A multiple-choice question has 2 to 6 distinct options, stored with ids `a` to `f`, and one correct option. A true/false question has fixed options `true` and `false`.
   - The answer key (`correct_option_ids`) is a separate column so candidate-facing code can leave it out explicitly. It's a list, so multiple-answer questions can be added later without a migration.
   - Marks are whole numbers from 1 to 100. Difficulty (easy, medium, hard) is optional.
8. **Archive rather than delete.**
   - An archived question isn't offered for new exams but stays for exams that already use it. It can be restored.
   - Deleting removes a question and all its versions and tags. It will be refused (409) once an exam uses it.
   - A subject with questions can't be deleted, and nor can a topic that questions are tagged with.

## Consequences

- Every bank change writes an audit entry (`question.created`, `revised`, `topics_set`, `archived`, `restored`, `deleted`). Entries never copy question text or answers.
- Questions list newest first, with cursor paging (`next_after`). A teacher's list covers only subjects they teach.
- AI drafts (Phase 4) will arrive as drafts outside the bank. Approving one creates a question with its own `source`, so the bank only ever holds teacher-approved content.

## Still open

- Importing questions in bulk (for example from a spreadsheet).
- Images and diagrams in questions, which wait for the diagram engine.
- Other question types: multiple-answer, short answer, and essays with manual marking.
