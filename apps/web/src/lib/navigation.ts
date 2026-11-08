import {
  Award,
  BookOpen,
  CalendarDays,
  ClipboardCheck,
  ClipboardList,
  FileQuestion,
  FileText,
  LayoutDashboard,
  PencilLine,
  Presentation,
  School,
  ScrollText,
  Sparkles,
  UserPlus,
  UserRound,
  Users,
  type LucideIcon,
} from "lucide-react";

import type { SchoolRole, SessionInfo } from "@/lib/types";

type SignedInUser = NonNullable<SessionInfo["user"]>;

export interface NavItem {
  href: string;
  label: string;
  icon: LucideIcon;
  roles: SchoolRole[];
  /** A further condition beyond the role, such as being an exam coordinator. */
  when?: (user: SignedInUser) => boolean;
}

export interface NavGroup {
  label?: string;
  items: NavItem[];
}

const EVERYONE: SchoolRole[] = ["school_admin", "teacher", "student"];
const STAFF: SchoolRole[] = ["school_admin", "teacher"];
const STUDENTS: SchoolRole[] = ["student"];
const ADMINS: SchoolRole[] = ["school_admin"];

// Each role sees only the screens it can use. The API still checks every request: hiding a link
// is a convenience, not access control.
export const NAV_GROUPS: NavGroup[] = [
  { items: [{ href: "/dashboard", label: "Dashboard", icon: LayoutDashboard, roles: EVERYONE }] },
  {
    items: [
      { href: "/my-exams", label: "My exams", icon: PencilLine, roles: STUDENTS },
      { href: "/my-results", label: "My results", icon: Award, roles: STUDENTS },
    ],
  },
  {
    label: "Exams",
    items: [
      { href: "/exams", label: "Exams", icon: ClipboardList, roles: STAFF },
      {
        href: "/approvals",
        label: "Approvals",
        icon: ClipboardCheck,
        roles: STAFF,
        when: (user) => user.role === "school_admin" || user.is_exam_coordinator,
      },
    ],
  },
  {
    label: "Question bank",
    items: [
      { href: "/questions", label: "Questions", icon: FileQuestion, roles: STAFF },
      { href: "/passages", label: "Passages", icon: ScrollText, roles: STAFF },
      { href: "/materials", label: "Learning materials", icon: FileText, roles: STAFF },
      { href: "/drafting", label: "AI drafts", icon: Sparkles, roles: STAFF },
    ],
  },
  {
    label: "School setup",
    items: [
      { href: "/school/accounts", label: "Accounts", icon: Users, roles: ADMINS },
      { href: "/school/calendar", label: "Sessions and terms", icon: CalendarDays, roles: ADMINS },
      { href: "/school/classes", label: "Classes", icon: School, roles: ADMINS },
      { href: "/school/subjects", label: "Subjects", icon: BookOpen, roles: ADMINS },
      { href: "/school/enrolment", label: "Enrolment", icon: UserPlus, roles: ADMINS },
      { href: "/school/teaching", label: "Teaching", icon: Presentation, roles: ADMINS },
    ],
  },
  { items: [{ href: "/account", label: "Account", icon: UserRound, roles: EVERYONE }] },
];

export function navFor(user: SignedInUser): NavGroup[] {
  return NAV_GROUPS.map((group) => ({
    ...group,
    items: group.items.filter((item) => item.roles.includes(user.role) && (item.when?.(user) ?? true)),
  })).filter((group) => group.items.length > 0);
}
