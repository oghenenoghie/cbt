/**
 * What the lab app's window can ask the main process for, and what it gets back. The window holds
 * no keys and decides nothing: every call is checked in the main process (src/main/bridge.ts).
 */

export type QuestionType =
  | "mcq_single"
  | "mcq_multiple"
  | "true_false"
  | "short_answer"
  | "numeric"
  | "essay";

export interface DeviceSummary {
  name: string;
  school: { code: string; name: string };
  /** "online": registered with a code over the internet; "file": by USB. */
  method: "online" | "file";
  server: string | null;
  registered_at: string;
}

export interface LabStatus {
  registered: boolean;
  /** A USB registration waiting for its setup file. */
  pending_file_registration: { name: string; request_saved: boolean } | null;
  device: DeviceSummary | null;
  /** The exam room lock: full screen, can't be left without the lab PIN. */
  locked: boolean;
  /** The staff side is open (the lab PIN was given). */
  staff: boolean;
  /** Whether this computer's secrets are encrypted at rest (Windows DPAPI). */
  secure_storage: boolean;
}

export type RoomExamState = "open" | "upcoming" | "closed" | "withdrawn";

export interface RoomExam {
  exam_id: string;
  title: string;
  subject: string;
  opens_at: string;
  closes_at: string;
  duration_minutes: number;
  question_count: number;
  total_marks: number;
  instant_scores: boolean;
  state: RoomExamState;
}

export interface SignedIn {
  exam: RoomExam & { instructions: string | null; max_attempts: number };
  student: { name: string; class_name: string | null; username: string };
  /** An attempt already started on this computer, to carry on with. */
  resume: boolean;
  attempts_left: number;
}

export interface SittingQuestion {
  item_id: string;
  number: number;
  type: QuestionType;
  stem: string;
  options: { id: string; text: string }[];
  marks: number;
  passage: { title: string; body: string } | null;
}

export interface GivenAnswer {
  selected: string[];
  text: string | null;
}

export interface Sitting {
  attempt_id: string;
  exam_title: string;
  subject: string;
  student_name: string;
  ends_at: string;
  seconds_left: number;
  questions: SittingQuestion[];
  answers: Record<string, GivenAnswer>;
}

export interface Finished {
  student_name: string;
  exam_title: string;
  reason: "student" | "time_up";
  answered: number;
  question_count: number;
  /** Only for exams with instant scores; null otherwise. */
  score: number | null;
  max_score: number | null;
  /** Written answers a teacher will mark (instant-score exams only). */
  to_mark: number;
}

export type ResultStatus = "waiting" | "accepted" | "conflict" | "rejected" | "refused";

export interface StaffResult {
  submission_id: string;
  exam_title: string;
  student_name: string;
  finished_at: string;
  status: ResultStatus;
  reason: string | null;
  flags: string[];
  saved_to_usb_at: string | null;
  sent_at: string | null;
}

export interface StaffExam {
  exam_id: string;
  title: string;
  subject: string;
  opens_at: string;
  closes_at: string;
  state: RoomExamState;
  source: "online" | "usb";
  received_at: string;
  students: number;
  in_progress: number;
  finished: number;
}

export interface SyncReport {
  at: string;
  ok: boolean;
  message: string;
}

export interface LabAppStatus {
  version: string;
  /** A newer version, downloaded and checked, waiting to be installed. */
  update: { version: string; notes: string | null; size: number } | null;
  /** Why the last check for an update failed, if it did. */
  update_problem: string | null;
  /** Why installing must wait (students still sitting), or null. */
  install_blocked: string | null;
}

export interface StaffOverview {
  device: DeviceSummary;
  exams: StaffExam[];
  results: StaffResult[];
  last_sync: SyncReport | null;
  app: LabAppStatus;
}

/** Every call the window can make, with its input and result. */
export interface LabCalls {
  status: [void, LabStatus];
  registerOnline: [
    { server: string; school_code: string; registration_code: string; name: string; pin: string },
    LabStatus,
  ];
  startFileRegistration: [{ name: string; pin: string }, LabStatus];
  saveRegistrationRequest: [void, { saved_to: string } | null];
  finishFileRegistration: [void, LabStatus | null];
  cancelFileRegistration: [void, LabStatus];
  roomExams: [void, RoomExam[]];
  signIn: [{ exam_id: string; username: string; code: string }, SignedIn];
  signOut: [void, void];
  begin: [void, Sitting];
  sitting: [void, Sitting];
  answer: [{ item_id: string; selected: string[]; text: string | null }, { saved_at: string }];
  handIn: [void, Finished];
  unlock: [{ pin: string }, LabStatus];
  lock: [void, LabStatus];
  overview: [void, StaffOverview];
  syncNow: [void, StaffOverview];
  loadPackageFile: [void, { title: string } | null];
  saveResultsFile: [{ scope: "unsent" | "all" }, { saved_to: string; count: number } | null];
  changePin: [{ current: string; next: string }, void];
  installUpdate: [void, void];
  quit: [void, void];
}

export type LabMethod = keyof LabCalls;

export type LabReply<T> = { ok: true; value: T } | { ok: false; error: string };

/** What the preload script exposes as `window.lab`. */
export interface LabBridge {
  call<M extends LabMethod>(method: M, input: LabCalls[M][0]): Promise<LabReply<LabCalls[M][1]>>;
}
