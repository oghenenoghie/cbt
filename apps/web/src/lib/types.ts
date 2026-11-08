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
  enrolments: { session: SessionRef; arm_id: string; arm_name: string; subjects: SubjectRef[] }[];
  teaching: { session: SessionRef; arm_id: string; arm_name: string; subject: SubjectRef }[];
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

export type QuestionType = "mcq_single" | "true_false";
export type Difficulty = "easy" | "medium" | "hard";
export type BankStatus = "active" | "archived";

export interface QuestionOption {
  id: string;
  text: string;
}

/** One version of a question, as staff see it: the answer key is included. */
export interface QuestionVersion {
  version: number;
  type: QuestionType;
  stem: string;
  options: QuestionOption[];
  correct_option_ids: string[];
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
  /** "manual" for now; AI drafts will add their own source. */
  source: string;
  topic_ids: string[];
  latest_version: number;
  latest: QuestionVersion;
  created_at: string;
  updated_at: string;
}

/** What a teacher writes: `correct` is the right option's position, or true/false. */
export interface QuestionContent {
  type: QuestionType;
  stem: string;
  options: string[] | null;
  correct: number | boolean;
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
  marks: number;
}

export interface PaperBlock {
  block: number;
  passage: { passage_id: string; version: number; title: string; body: string } | null;
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
  score: number | null;
  max_score: number;
}
