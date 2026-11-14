// Shapes the API returns (backend/api/app/*/schemas.py). Keep in step with the backend.

export type SchoolRole = "school_admin" | "teacher" | "student";

export interface SessionInfo {
  kind: "school_user" | "platform_admin";
  csrf_token: string;
  expires_at: string;
  user: {
    id: string;
    username: string;
    display_name: string;
    role: SchoolRole;
    is_exam_coordinator: boolean;
  } | null;
  school: { id: string; name: string; code: string } | null;
  platform_admin: { id: string; email: string; display_name: string } | null;
}

export interface SessionRef {
  id: string;
  name: string;
  is_current: boolean;
}

export interface SubjectRef {
  id: string;
  name: string;
  code: string | null;
}

export interface MyClasses {
  enrolments: {
    session: SessionRef;
    arm_id: string;
    arm_name: string;
    subjects: SubjectRef[];
  }[];
  teaching: {
    session: SessionRef;
    arm_id: string;
    arm_name: string;
    subject: SubjectRef;
  }[];
}

export const ROLE_LABELS: Record<SchoolRole, string> = {
  school_admin: "School admin",
  teacher: "Teacher",
  student: "Student",
};

// --- School setup (school admins) ---------------------------------------------------------------

export type AccountStatus = "active" | "disabled";

export interface Account {
  id: string;
  username: string;
  display_name: string;
  email: string | null;
  role: SchoolRole;
  status: AccountStatus;
  is_exam_coordinator: boolean;
  has_password: boolean;
  created_at: string;
}

export interface AccountList {
  users: Account[];
  next_after: string | null;
}

export interface ImportedAccount extends Account {
  /** Only for rows whose password the import generated. Shown once, never stored readable. */
  generated_password: string | null;
}

export interface Term {
  id: string;
  name: string;
  position: number;
  starts_on: string | null;
  ends_on: string | null;
}

export interface AcademicSession {
  id: string;
  name: string;
  starts_on: string;
  ends_on: string;
  is_current: boolean;
  terms: Term[];
}

export interface ClassLevel {
  id: string;
  name: string;
  position: number;
}

export interface ClassArm {
  id: string;
  session_id: string;
  level_id: string;
  level_name: string;
  name: string;
  /** For example "JSS1 A". */
  display_name: string;
}

export interface Topic {
  id: string;
  name: string;
  position: number;
}

export interface Subject {
  id: string;
  name: string;
  code: string | null;
  level_ids: string[];
  topics: Topic[];
}

export interface Enrolment {
  id: string;
  session_id: string;
  arm_id: string;
  candidate_id: string;
  user_id: string | null;
  username: string | null;
  display_name: string;
}

export interface Assignment {
  id: string;
  teacher_id: string;
  teacher_name: string;
  session_id: string;
  arm_id: string;
  arm_name: string;
  subject_id: string;
  subject_name: string;
}

// --- Question bank (school admins, and teachers of the subject) ---------------------------------

export type QuestionType =
  | "mcq_single"
  | "mcq_multiple"
  | "true_false"
  | "short_answer"
  | "numeric"
  | "essay";
/** The types AI drafts are written in so far (ADR 0005, ADR 0006). */
export type AiQuestionType = "mcq_single" | "true_false";
export type Difficulty = "easy" | "medium" | "hard";
export type BankStatus = "active" | "archived";

export interface QuestionOption {
  id: string;
  text: string;
}

/**
 * The answer key of a question answered in writing: the accepted answers (short answer), the
 * number and how far from it still counts (numeric), or the marking guide (essay). Staff only.
 */
export interface AnswerKey {
  accepted_answers?: string[];
  value?: number;
  tolerance?: number;
  guide?: string;
}

/** One version of a question, as staff see it: the answer key is included. */
export interface QuestionVersion {
  version: number;
  type: QuestionType;
  stem: string;
  options: QuestionOption[];
  correct_option_ids: string[];
  answer_key: AnswerKey | null;
  explanation: string | null;
  marks: number;
  difficulty: Difficulty | null;
  created_by_id: string | null;
  created_at: string;
}

export interface Question {
  id: string;
  subject_id: string;
  passage_id: string | null;
  status: BankStatus;
  /** "manual", or "ai" for an approved AI draft (ADR 0005). */
  source: string;
  topic_ids: string[];
  latest_version: number;
  latest: QuestionVersion;
  created_at: string;
  updated_at: string;
}

/**
 * What a teacher writes. `correct` is the right option's position (`mcq_single`), the right
 * options' positions (`mcq_multiple`) or true/false; the written types use `accepted_answers`,
 * `value` and `tolerance`, or `guide` instead. What a type doesn't use is null.
 */
export interface QuestionContent {
  type: QuestionType;
  stem: string;
  options: string[] | null;
  correct: number | number[] | boolean | null;
  accepted_answers: string[] | null;
  value: number | null;
  tolerance: number | null;
  guide: string | null;
  explanation: string | null;
  marks: number;
  difficulty: Difficulty | null;
}

export interface PassageVersion {
  version: number;
  title: string;
  body: string;
  created_by_id: string | null;
  created_at: string;
}

export interface Passage {
  id: string;
  subject_id: string;
  status: BankStatus;
  latest_version: number;
  latest: PassageVersion;
  /** Its active questions, in the order they were written. */
  question_ids: string[];
  created_at: string;
  updated_at: string;
}

// --- Exams (staff) -----------------------------------------------------------------------------

/** draft → submitted → published (or back to draft when sent back); published → withdrawn. */
export type ExamStatus = "draft" | "submitted" | "published" | "withdrawn";
export type ResultsRelease = "teacher" | "immediate";
/** What the signed-in person may do with an exam now: a hint; the API checks every action. */
export type ExamAction =
  | "edit"
  | "submit"
  | "delete"
  | "publish"
  | "return"
  | "withdraw"
  | "release_results"
  | "copy";

export interface ExamItem {
  position: number;
  question_id: string | null;
  passage_id: string | null;
}

export interface Exam {
  id: string;
  subject_id: string;
  term_id: string;
  level_id: string;
  arm_ids: string[];
  title: string;
  instructions: string | null;
  duration_minutes: number;
  opens_at: string;
  closes_at: string;
  max_attempts: number;
  shuffle_questions: boolean;
  shuffle_options: boolean;
  results_release: ResultsRelease;
  status: ExamStatus;
  /** The approver's note when it was last sent back, or the reason it was withdrawn. */
  review_note: string | null;
  created_by_id: string;
  created_by_name: string;
  reviewed_by_id: string | null;
  reviewed_by_name: string | null;
  reviewed_at: string | null;
  submitted_at: string | null;
  published_at: string | null;
  withdrawn_at: string | null;
  results_released_at: string | null;
  copied_from_id: string | null;
  items: ExamItem[];
  allowed_actions: ExamAction[];
  created_at: string;
  updated_at: string;
}

/** The settings an exam is created or edited with. Times are ISO strings with a zone. */
export interface ExamSettings {
  title: string;
  instructions: string | null;
  duration_minutes: number;
  opens_at: string;
  closes_at: string;
  max_attempts: number;
  shuffle_questions: boolean;
  shuffle_options: boolean;
  results_release: ResultsRelease;
}

/** A question as it appears on the paper, with its answer. Staff only. */
export interface PaperQuestion {
  position: number;
  question_id: string;
  version: number;
  type: QuestionType;
  stem: string;
  options: QuestionOption[];
  correct_option_ids: string[];
  answer_key: AnswerKey | null;
  marks: number;
}

export interface PaperBlock {
  block: number;
  passage: {
    passage_id: string;
    version: number;
    title: string;
    body: string;
  } | null;
  questions: PaperQuestion[];
}

export interface Paper {
  exam_id: string;
  /** True once submitted: pinned to exact versions. A draft's paper shows the latest versions. */
  frozen: boolean;
  question_count: number;
  total_marks: number;
  blocks: PaperBlock[];
  /** For a draft, what stops it being submitted. */
  problems: string[];
}

/** An attempt as staff see it while following an exam. */
export interface AttemptSummary {
  id: string;
  candidate_id: string;
  candidate_name: string;
  number: number;
  status: "in_progress" | "submitted";
  started_at: string;
  ends_at: string;
  submitted_at: string | null;
  /** "student" when they submitted, "time_up" when the clock ran out. */
  submitted_reason: string | null;
  answered_count: number;
  question_count: number;
  /** With teachers' marks, once submitted. */
  score: number | null;
  max_score: number;
  /** Written answers waiting for a teacher's mark. */
  pending_marking: number;
}

// --- Students: sitting exams and results -----------------------------------------------------
// None of these carry answer keys or explanations: the API never sends them to students.

export interface MyExam {
  id: string;
  title: string;
  instructions: string | null;
  subject_id: string;
  subject_name: string;
  opens_at: string;
  closes_at: string;
  duration_minutes: number;
  question_count: number;
  total_marks: number;
  max_attempts: number;
  attempts_used: number;
  state: "upcoming" | "open" | "closed";
  /** The attempt to resume, if one is under way. */
  attempt_in_progress_id: string | null;
  can_start: boolean;
  /** Whether a result is available for you now. */
  result_available: boolean;
}

export interface AttemptQuestion {
  item_id: string;
  number: number;
  type: QuestionType;
  stem: string;
  /** In this student's order. Empty for questions answered in writing. */
  options: QuestionOption[];
  marks: number;
  selected_option_ids: string[];
  /** The saved answer to a short-answer, number or essay question. */
  text: string | null;
}

export interface AttemptBlock {
  passage: { title: string; body: string } | null;
  questions: AttemptQuestion[];
}

export interface Attempt {
  id: string;
  exam_id: string;
  exam_title: string;
  number: number;
  status: "in_progress" | "submitted";
  started_at: string;
  ends_at: string;
  /** The server's clock when it answered. */
  server_now: string;
  seconds_left: number;
  submitted_at: string | null;
  /** "student" or "time_up". */
  submitted_reason: string | null;
  question_count: number;
  answered_count: number;
  /** The paper while the attempt is in progress; empty once it's submitted. */
  blocks: AttemptBlock[];
}

export interface MyResult {
  exam_id: string;
  exam_title: string;
  subject_id: string;
  subject_name: string;
  closes_at: string;
  attempt_id: string;
  attempt_number: number;
  attempts_used: number;
  submitted_at: string;
  submitted_reason: string;
  score: number;
  max_score: number;
  percentage: number;
  /** Whether the question-by-question review is available (results visible and the exam closed). */
  review_available: boolean;
}

/** One of the student's own answers, marked right or wrong. Never the correct option. */
export interface ReviewQuestion {
  number: number;
  type: QuestionType;
  stem: string;
  options: QuestionOption[];
  selected_option_ids: string[];
  /** What the student wrote, for questions answered in writing. */
  text: string | null;
  /** Full marks. A written answer can also score part of its marks. */
  is_correct: boolean;
  score: number;
  marks: number;
  /** The teacher's comment on a marked answer. */
  comment: string | null;
}

export interface MyResultDetail extends MyResult {
  blocks: {
    passage: { title: string; body: string } | null;
    questions: ReviewQuestion[];
  }[];
}

// --- Results for staff (answer keys included) -------------------------------------------------

export interface StudentResult {
  candidate_id: string;
  candidate_name: string;
  /** The student's class for the exam's session; null if they've since left the exam's classes. */
  arm_id: string | null;
  arm_name: string | null;
  status: "not_sat" | "in_progress" | "submitted";
  attempts_used: number;
  counted_attempt_id: string | null;
  counted_attempt_number: number | null;
  /** With teachers' marks; answers still waiting count as 0. */
  score: number | null;
  percentage: number | null;
  /** Written answers in the counted attempt waiting for a teacher's mark. */
  pending_marking: number;
}

export interface ExamResults {
  exam_id: string;
  results_release: ResultsRelease;
  results_released_at: string | null;
  max_score: number;
  /** Answers still to mark across the counted attempts. Results can't be released until it's 0. */
  pending_marking: number;
  summary: {
    students: number;
    sat: number;
    not_sat: number;
    average_percentage: number | null;
    highest_percentage: number | null;
    lowest_percentage: number | null;
  };
  students: StudentResult[];
}

/** How one question did across the counted attempts. */
export interface ItemStat {
  position: number;
  block: number;
  question_id: string;
  version: number;
  type: QuestionType;
  stem: string;
  passage_title: string | null;
  marks: number;
  correct_option_ids: string[];
  answer_key: AnswerKey | null;
  answered: number;
  /** How many got full marks. */
  correct: number;
  /** The marks scored as a percentage of those available (for right-or-wrong questions, the
   * percentage of counted attempts that got it right). */
  facility: number;
  /** How many chose each option, by option id. */
  option_counts: Record<string, number>;
  pending_marking: number;
}

export interface ItemAnalysis {
  exam_id: string;
  attempts_counted: number;
  items: ItemStat[];
}

/** A teacher's mark for a written answer. */
export interface TeacherMark {
  score: number;
  comment: string | null;
  marked_by_id: string | null;
  marked_by_name: string | null;
  marked_at: string;
}

export interface ScriptQuestion {
  position: number;
  item_id: string;
  response_id: string;
  question_id: string;
  version: number;
  type: QuestionType;
  stem: string;
  options: QuestionOption[];
  correct_option_ids: string[];
  answer_key: AnswerKey | null;
  selected_option_ids: string[];
  text: string | null;
  /** What counts: the teacher's mark if there is one, else the automatic one. */
  is_correct: boolean;
  score: number;
  marks: number;
  /** What automatic marking gave. */
  auto_score: number;
  pending_marking: boolean;
  mark: TeacherMark | null;
}

/** One student's marked attempt, with the answer key. Staff only. */
export interface Script {
  attempt_id: string;
  exam_id: string;
  candidate_id: string;
  candidate_name: string;
  number: number;
  submitted_at: string;
  submitted_reason: string;
  score: number;
  max_score: number;
  percentage: number;
  pending_marking: number;
  questions: ScriptQuestion[];
}

// --- Marking written answers (ADR 0006) -------------------------------------------------------

export interface MarkingQuestion {
  item_id: string;
  position: number;
  block: number;
  question_id: string;
  version: number;
  type: QuestionType;
  stem: string;
  passage_title: string | null;
  marks: number;
  answer_key: AnswerKey | null;
  /** Of the counted attempts: answers given, marked by a teacher, and waiting. */
  answered: number;
  marked: number;
  pending: number;
}

export interface MarkingOverview {
  exam_id: string;
  results_release: ResultsRelease;
  results_released_at: string | null;
  /** Whether you may give marks now. */
  can_mark: boolean;
  /** Why marks can't be given or changed now. */
  locked_reason: string | null;
  pending: number;
  questions: MarkingQuestion[];
}

export interface MarkingAnswer {
  response_id: string;
  attempt_id: string;
  attempt_number: number;
  candidate_id: string;
  candidate_name: string;
  text: string | null;
  auto_score: number;
  auto_correct: boolean;
  /** What counts now. */
  score: number;
  pending: boolean;
  mark: TeacherMark | null;
}

export interface MarkingAnswers {
  exam_id: string;
  question: MarkingQuestion;
  can_mark: boolean;
  locked_reason: string | null;
  answers: MarkingAnswer[];
}

// Learning materials (ADR 0004) --------------------------------------------------------------

export type VersionStatus = "queued" | "processing" | "extracted" | "failed" | "approved" | "rejected";

export interface DocumentVersion {
  version: number;
  filename: string;
  /** What the file turned out to be: "pdf", "docx" or "txt". */
  kind: string;
  content_type: string;
  size_bytes: number;
  sha256: string;
  note: string | null;
  status: VersionStatus;
  attempts: number;
  segment_count: number | null;
  char_count: number | null;
  /** What the reviewer must know before approving, e.g. pages with no readable text. */
  warnings: string[];
  /** Why processing failed, in words a teacher can act on. */
  error: string | null;
  uploaded_by_id: string | null;
  uploaded_by_name: string | null;
  created_at: string;
  processed_at: string | null;
  reviewed_by_id: string | null;
  reviewed_by_name: string | null;
  reviewed_at: string | null;
  review_note: string | null;
}

export interface LearningDocument {
  id: string;
  subject_id: string;
  title: string;
  description: string | null;
  status: BankStatus;
  topic_ids: string[];
  latest_version: number;
  latest: DocumentVersion;
  /** The newest approved version: the one used as evidence for AI drafts. */
  approved_version: number | null;
  created_by_id: string | null;
  created_by_name: string | null;
  created_at: string;
  updated_at: string;
}

export interface LearningDocumentDetail extends LearningDocument {
  /** Every version, newest first. */
  versions: DocumentVersion[];
}

export interface DocumentSegment {
  position: number;
  /** "page" (PDF), "section" (Word), "slide", "sheet", "rows" (CSV), "lines" (text) or "image". */
  kind: "page" | "section" | "slide" | "sheet" | "rows" | "lines" | "image";
  number: number;
  /** The chapter or heading it falls under. */
  label: string | null;
  text: string;
  char_count: number;
  /** "text" from the file itself, or "ocr" read from a picture. */
  method: string;
  /** OCR's confidence, from 0 to 1. */
  confidence: number | null;
  /** "no_text" (nothing readable) or "low_confidence" (OCR unsure: never used for AI drafts). */
  flags: string[];
}

export interface SegmentPage {
  segments: DocumentSegment[];
  next_after: number | null;
}

// AI question drafts (ADR 0005) ----------------------------------------------------------------

export type AiRequestStatus = "queued" | "processing" | "done" | "failed";
export type DraftStatus = "pending" | "approved" | "dismissed" | "rejected";

export interface AiUsage {
  model: string | null;
  provider_calls: number;
  input_tokens: number;
  output_tokens: number;
  cache_read_tokens: number;
  cache_write_tokens: number;
  /** An estimate from the server's configured prices, in US dollars. */
  cost_usd: number;
  latency_ms: number;
}

export interface AiSource {
  label: string;
  segment_id: string;
  document_id: string;
  document_title: string;
  version: number;
  location: string;
  char_count: number;
  score: number;
  /** The text the model was given. */
  text: string;
}

export interface DraftCitation {
  position: number;
  source_label: string;
  segment_id: string | null;
  document_id: string | null;
  document_title: string | null;
  location: string | null;
  quote: string;
  /** Found word for word in the material it names. Only found quotes count. */
  found: boolean;
}

export interface AnswerCheck {
  supported: boolean;
  single_answer: boolean;
  clear: boolean;
  in_scope: boolean;
  assessment: string;
}

/** A draft with its answer key: staff only. */
export interface QuestionDraft {
  id: string;
  request_id: string;
  subject_id: string;
  position: number;
  status: DraftStatus;
  /** A question type, or what the model wrote for a rejected one. */
  type: string;
  stem: string;
  options: QuestionOption[];
  correct_option_ids: string[];
  explanation: string | null;
  marks: number;
  difficulty: Difficulty | null;
  topic_ids: string[];
  /** Why a rejected draft failed the checks. */
  reasons: string[];
  answer_check: AnswerCheck | null;
  citations: DraftCitation[];
  edited_by_id: string | null;
  edited_at: string | null;
  reviewed_by_id: string | null;
  reviewed_at: string | null;
  review_note: string | null;
  /** The bank question an approved draft became. */
  question_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface AiRequest {
  id: string;
  subject_id: string;
  requested_by_id: string | null;
  requested_by_name: string | null;
  question_types: AiQuestionType[];
  count: number;
  difficulty: Difficulty | null;
  marks: number;
  topic_ids: string[];
  document_ids: string[];
  objective: string | null;
  status: AiRequestStatus;
  error: string | null;
  accepted_count: number;
  rejected_count: number;
  /** The shortfall report, as sentences. */
  notes: string[];
  usage: AiUsage;
  created_at: string;
  finished_at: string | null;
}

export interface AiRequestDetail extends AiRequest {
  sources: AiSource[];
  /** Every candidate in the order written. */
  drafts: QuestionDraft[];
}

export interface QuestionCitation {
  version: number;
  position: number;
  segment_id: string;
  document_id: string;
  document_title: string;
  document_version: number;
  location: string;
  quote: string;
}
