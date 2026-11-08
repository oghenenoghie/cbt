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
