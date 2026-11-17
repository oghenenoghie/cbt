import { redirect } from "next/navigation";

/** The integrations workspace now lives inside the authenticated school-admin shell. */
export default function IntegrationsRedirect() {
  redirect("/school/integrations");
}
