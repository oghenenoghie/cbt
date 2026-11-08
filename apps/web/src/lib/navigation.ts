import { LayoutDashboard, UserRound, type LucideIcon } from "lucide-react";

import type { SchoolRole } from "@/lib/types";

export interface NavItem {
  href: string;
  label: string;
  icon: LucideIcon;
  roles: SchoolRole[];
}

// Each role sees only the screens it can use. The API still checks every request: hiding a link
// is a convenience, not access control.
export const NAV_ITEMS: NavItem[] = [
  { href: "/dashboard", label: "Dashboard", icon: LayoutDashboard, roles: ["school_admin", "teacher", "student"] },
  { href: "/account", label: "Account", icon: UserRound, roles: ["school_admin", "teacher", "student"] },
];

export function navFor(role: SchoolRole): NavItem[] {
  return NAV_ITEMS.filter((item) => item.roles.includes(role));
}
