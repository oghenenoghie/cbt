import {
  BookOpen,
  CalendarDays,
  LayoutDashboard,
  Presentation,
  School,
  UserPlus,
  UserRound,
  Users,
  type LucideIcon,
} from "lucide-react";

import type { SchoolRole } from "@/lib/types";

export interface NavItem {
  href: string;
  label: string;
  icon: LucideIcon;
  roles: SchoolRole[];
}

export interface NavGroup {
  label?: string;
  items: NavItem[];
}

const EVERYONE: SchoolRole[] = ["school_admin", "teacher", "student"];
const ADMINS: SchoolRole[] = ["school_admin"];

// Each role sees only the screens it can use. The API still checks every request: hiding a link
// is a convenience, not access control.
export const NAV_GROUPS: NavGroup[] = [
  { items: [{ href: "/dashboard", label: "Dashboard", icon: LayoutDashboard, roles: EVERYONE }] },
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

export function navFor(role: SchoolRole): NavGroup[] {
  return NAV_GROUPS.map((group) => ({
    ...group,
    items: group.items.filter((item) => item.roles.includes(role)),
  })).filter((group) => group.items.length > 0);
}
