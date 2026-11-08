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
