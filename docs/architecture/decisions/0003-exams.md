# ADR 0003: Exams and the question bank

- **Status:** Accepted (the question bank and exam builder are built; sitting exams and results follow)
- **Date:** 2026-11-07 (decision 2 revised 2026-11-08: exam coordinators approve exams)
- **Implemented in:**
  - question bank: `backend/api/app/models/questions.py`, `backend/api/app/questions/` (migrations `0006_question_bank` and `0007_passages`)
  - exam builder and publishing: `backend/api/app/models/exams.py`, `backend/api/app/exams/`; the coordinator designation in `backend/api/app/accounts/` (migration `0008_exams`)

## Context

With the school foundation in place (ADRs 0001 and 0002), the next product step is a basic exam workflow, built before documents and AI so the AI work has a question bank and exams to feed. The product docs list the parts (question bank, exam builder, exam delivery, grading, results) and the integrity rules (immutable published snapshots, append-only answer events, no answer keys or early results for candidates). They didn't say who publishes, how results are released, how many attempts students get, or whether order is shuffled. Those were settled before building.

The work is built in four stages, each its own change:

- **A. Question bank:** single-answer multiple-choice and true/false questions, and reading passages with the questions that follow them, all versioned. (Built.)
- **B. Exam builder and publishing:** a teacher or school admin prepares an exam for one or more arms and submits it; an exam coordinator (or, for a teacher's exam, a school admin) approves and publishes it, freezing a snapshot. (Built.)
- **C. Sitting an exam:** start and resume, a server-side timer, append-only answer events, submission and auto-grading.
- **D. Results:** release, students' own results, and item analysis.

## Decisions

1. **Results are released by the teacher.**
   - Scores stay hidden from students until the exam's teacher (or a school admin) releases them.
   - A teacher can choose "show results immediately" for an exam instead, for example for a practice test.
   - Candidate-facing endpoints check this before returning anything about a result.
2. **Publishing needs approval from someone other than the exam's author.**
   - A teacher or school admin prepares an exam and submits it. An approver publishes it, or sends it back with a note.
   - **Exam coordinators approve exams.** Being a coordinator is a designation on a staff account, not a separate role: a school admin marks teachers or school admins as exam coordinators, and they keep their own role and classes. A school can have several.
   - A **school admin can also approve a teacher's exam**. An exam prepared by a school admin must be approved by an exam coordinator.
   - **Nobody approves an exam they prepared**, including coordinators. A coordinator's own exam goes to another coordinator or, if they're a teacher, to a school admin.
   - One exam can be set for several arms, as long as they're at the same level and take the exam's subject. The author must be allowed to teach each one (`require_teaching`, ADR 0002).
   - Publishing freezes an **immutable snapshot**: the exact question and passage versions, their order, marks and settings. Later edits to the bank or the exam template never change a published exam.
   - **A published exam can't be edited.** Before it opens, an approver can withdraw it, and a corrected copy goes through approval again.
3. **One timed attempt by default.**
   - An exam has an availability window and a duration. A student gets one attempt. The teacher can allow more.
   - An attempt can be resumed (after a crash or a lost connection), but the clock keeps running from when it started. The server owns the clock; the client's timer is only a display.
   - When time runs out, the attempt is submitted with the answers saved so far.
4. **Question and option order are shuffled per student by default.**
   - Each attempt gets its own order, chosen once at the start and kept on resume. Teachers can turn shuffling off for an exam.
   - True/false options are never shuffled.
   - A passage's questions stay together, straight after the passage, in the order they were written. The passage and its questions move as one block when the exam's question order is shuffled. Each question's options are still shuffled.
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
8. **Reading passages: "read the passage and answer the questions that follow".**
   - A passage is a titled text (up to 20,000 characters, paragraphs kept) in one subject. It's versioned like a question: editing adds a version, and stored versions never change.
   - A question can be written for a passage of its own subject. The link is set when the question is written and doesn't change. The database enforces the same school and subject: questions reference their passage by `(id, subject_id, tenant_id)`.
   - A passage lists its active questions in the order they were written. An archived passage takes no new questions; its existing questions are unchanged.
   - A passage with questions can't be deleted. Archive it, or delete its questions first.
   - The same people who can use a subject's questions can use its passages, under the same rules.
   - A published exam (Exams B) pins the passage version current at publishing, alongside its question versions, so later edits to the passage don't reach it.
9. **Archive rather than delete.**
   - An archived question isn't offered for new exams but stays for exams that already use it. It can be restored.
   - Deleting removes a question and all its versions and tags. It's refused (409) once an exam uses it.
   - A subject with questions can't be deleted, and nor can a topic that questions are tagged with.

10. **How an exam moves from draft to published (Exams B).**
   - An exam has one subject, one term, and one or more classes at one level in that term's session. The level must take the subject. Subject and term are fixed once created; copy the exam to change them.
   - Its items are an ordered list of questions and passages. A passage brings all its active questions, in the order they were written. A question that belongs to a passage can't be added on its own. Only active items of the exam's subject can be added, each once.
   - **Submitting freezes the paper**: every question is pinned to its current version (and its passage's version), with its marks, in order. The approver reviews exactly that paper. Changes to the bank afterwards don't reach it. Submission is refused, with the reasons, while an item is archived, a passage has no active questions, the exam is empty, the author no longer teaches every class, or the closing time has passed.
   - **Returning** an exam needs a note, discards the frozen paper and makes it a draft again. **Publishing** makes the paper final; it's refused once the closing time has passed.
   - **Withdrawing** needs a reason and is only possible before the exam opens. The author or anyone who could approve it can withdraw it. The withdrawn paper is kept for the record. **Copying** makes a new draft with the same settings and items, authored by whoever copies it, optionally for another term and its classes.
   - Only drafts can be deleted, by their author or a school admin.
   - **Who sees an exam:** school admins, exam coordinators, its author, and teachers who teach its subject to any of its classes. Students never see this side of an exam.
   - The database backs this up. A published paper's rows can't be changed or removed. A submitted or published exam's settings, classes and items can't change. A question, passage, subject, term, level or class that an exam uses can't be deleted.
   - A school admin can't change their own coordinator designation, just as they can't change their own role, so nobody grants themselves the right to approve exams.

## Consequences

- Every bank change writes an audit entry (`question.created`, `revised`, `topics_set`, `archived`, `restored`, `deleted`, and the same `passage.*` actions apart from topics). Entries never copy question text, passage text or answers.
- Questions and passages list newest first, with cursor paging (`next_after`). A teacher's list covers only subjects they teach.
- Every exam change writes an audit entry (`exam.created`, `updated`, `arms_set`, `items_set`, `submitted`, `returned`, `published`, `withdrawn`, `copied`, `deleted`). Notes and reasons aren't copied into the audit log.
- `allowed_actions` on each exam tells the interface what the signed-in person can do with it now. The server checks every action again.
- Exams C will read the frozen paper, never the editable exam, so what students sit is always what was approved.
- AI drafts (Phase 4) will arrive as drafts outside the bank. Approving one creates a question with its own `source`, so the bank only ever holds teacher-approved content.

## Still open

- Importing questions in bulk (for example from a spreadsheet).
- Images and diagrams in questions, which wait for the diagram engine.
- Other question types: multiple-answer, short answer, and essays with manual marking.
