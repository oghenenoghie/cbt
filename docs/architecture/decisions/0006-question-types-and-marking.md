# ADR 0006: More question types and teacher marking

- **Status:** Accepted. Stage A is built.
- **Date:** 2026-11-13
- **Implemented in:** `backend/api/app/questions/schemas.py`, `backend/api/app/attempts/marking.py`, `backend/api/app/results/marking.py`, `backend/api/app/results/service.py` (migration `0014_question_types_marking`)

## Context

The bank held two types: single-answer multiple choice and true/false (ADR 0003). Schools also set questions with several right options, one-word or one-number answers, and written answers that a teacher marks. ADR 0003 left "multiple-answer, short answer, and essays with manual marking" open.

Three choices were the user's, asked on 2026-11-13:

- **What a teacher gives a written answer:** a mark with an optional comment the student sees (chosen over a mark alone, or a rubric with criteria).
- **Multiple-answer questions:** all or nothing, full marks only for exactly the right options (chosen over part marks per option).
- **Who marks:** the subject's teachers and school admins, the same people who release results (chosen over admins only, or anyone who can see the exam).

Matching questions were left for later.

The work is built in stages:

- **A. The API:** the new types in the bank, sitting them, automatic marking, teacher marking, and teachers' marks in results. (Built.)
- **B. Web screens:** writing the new types, answering them while sitting, a marking screen, and marks and comments in results. (To come.)
- **C. AI drafts of the new types.** (To come.)

## Decisions

1. **Six question types.** A version's `type` is one of:
   - `mcq_single`: 2 to 6 options, one right (as before);
   - `mcq_multiple`: 2 to 6 options, one or more right;
   - `true_false` (as before);
   - `short_answer`: a word, name or phrase, with up to 10 accepted answers;
   - `numeric`: a number, with the answer and a tolerance;
   - `essay`: a written answer a teacher marks, with an optional marking guide (up to 10,000 characters).

   Choice types keep their key in `correct_option_ids`. The others keep theirs in the version's `answer_key` (`accepted_answers`, `value` and `tolerance`, or `guide`), which never changes, like the rest of a version. A field the type doesn't use is refused, so a question never carries a stray key. Staff responses include `answer_key`; student responses never do.

2. **Automatic marking** (`app/attempts/marking.py`), when an attempt is submitted:
   - **Choice questions:** full marks only for exactly the right options. A multiple-answer question gets nothing for some of the right options, or for the right ones plus a wrong one (the user's choice).
   - **Short answer:** right if it matches an accepted answer, ignoring case, spacing and surrounding punctuation. Spelling isn't forgiven: the teacher can mark it right instead (decision 4).
   - **Numeric:** right if within the tolerance (plus a hair, so 0.1 + 0.2 counts as 0.3). "9,8" reads as 9.8, and commas that group digits in threes are thousands separators, so "1,000" is 1000. Anything that isn't a plain number (words, "1e3", units) scores 0.
   - **Essay:** a non-blank answer scores 0 and waits for a teacher (`needs_marking`); a blank one scores 0 straight away.

   The attempt's stored `score` is the automatic total and, like the rest of a submitted attempt, never changes.

3. **Sitting the new types.** Choice questions are answered with `selected_option_ids` (several for `mcq_multiple`), the others with `text`: up to 500 characters for short answers and numbers, up to 20,000 for essays. The answer must fit the question's type. Blank text, like an empty list, clears the answer, and text is kept as typed. Multiple-answer options are shuffled like single-answer ones. The answer events and final responses keep the text, and stay append-only.

4. **Teacher marking.** Short answers, numbers and essays can be marked by a teacher; choice questions are only ever marked automatically.
   - **Who:** the exam's author, teachers who teach its subject to any of its classes, and school admins, the same as releasing (the user's choice). Exam coordinators who don't teach it can read the marking but not mark.
   - **What:** a whole mark from 0 to the question's marks, and an optional comment (up to 2,000 characters) that the student sees. It replaces the automatic mark, so a teacher can also accept a misspelt short answer or correct a number marked wrong. Blank answers can't be marked.
   - **Every mark is kept.** Marks are `ResponseMark` rows that never change, numbered per answer; marking again adds the next number and the highest counts. Two people marking the same answer at once can't both win: one gets a conflict and reloads. Saving the same mark and comment again adds nothing. Each mark writes an `answer.marked` audit entry with the score, the automatic score and the previous mark, never the answer or comment.
   - **When:** from the moment an attempt is submitted, while other students may still be sitting, until students can see the scores. Once results are released, marks are final. An exam that shows results immediately can't be re-marked at all, so an exam with essays must be set to release results by the teacher: submitting it for approval otherwise is refused.
   - **Endpoints:** `GET /exams/{id}/marking` (the written questions, with how many answers are marked and waiting), `GET /exams/{id}/marking/{item_id}` (every counted attempt's answer to one question, by student name) and `PUT /exams/{id}/marking/answers/{response_id}`.

5. **Results count teachers' marks** (`app/results/service.py`: `latest_marks`, `mark_of`, `totals`).
   - Class results, scripts, item analysis and students' results use the teacher's mark where there is one. They show how many answers still wait (`pending_marking`); until then, waiting answers count as 0.
   - **Results can't be released while any counted attempt's answers wait for marking.**
   - A written answer with part of its marks isn't counted as right. Item analysis's facility is the share of the available marks scored, which for right-or-wrong questions is the share of students who got it right, as before. Option counts for multiple-answer questions count each chosen option.
   - Scripts show the answer key or marking guide, the student's text, the automatic score, and the teacher's mark with who gave it and when.

6. **What students see.** Once the review is available (ADR 0003, decision 12), each answer shows their own text, their score, right or wrong, and the teacher's comment. Never the accepted answers, the expected number or the marking guide.

7. **AI drafts stay on two types for now.** Requests can ask for single-answer multiple choice and true/false only (ADR 0005, decision 9), and a draft can't be edited into another type. Drafting the new types, with checks that suit them, is stage C.

## Consequences

- A school can set a whole paper: objective questions marked at once, and written answers marked by its teachers before results go out.
- Results with written answers always wait for a teacher to finish marking and release them.
- The record shows every mark a written answer was given, by whom and when, and the automatic mark it replaced.
- Downgrading migration 0014 fails while any question of a new type exists.

## Still open

- Matching questions.
- Part marks for multiple-answer questions, if a school wants them per question.
- Rubrics with criteria, marking without seeing names, and second marking or moderation.
- Changing a mark after release (with ADR 0003's open question on re-marking after a wrong answer key).
- Units and significant figures for numbers, and forgiving small spelling slips in short answers automatically.
- Marking on the desktop app while offline.
