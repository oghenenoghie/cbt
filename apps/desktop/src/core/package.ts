/**
 * Exam packages as the server builds them (backend/api/app/offline/service.py `build_package`), and
 * the check every package passes before it is used: the server's signature, and the school.
 */

import { isEnvelope, verifyEnvelope, type EncryptedBlob, type Envelope } from "./crypto.js";
import type { QuestionType } from "./marking.js";
import type { DiagramSpec } from "../shared/api.js";

export const PACKAGE_FORMAT = "cbt-offline-package/1";

export interface PackageItem {
  item_id: string;
  position: number;
  block: number;
  passage_id: string | null;
  type: QuestionType;
  stem: string;
  diagram_spec?: DiagramSpec | null;
  options: { id: string; text: string }[];
  marks: number;
}

export interface PackageStudent {
  candidate_id: string;
  username: string | null;
  name: string;
  class_name: string | null;
  /** Attempts the server knew about when the package was made. */
  attempts_used: number;
  code: { salt: string; hash: string; iterations: number } | null;
}

export interface ExamPackage {
  package_id: string;
  issued_at: string;
  device_id: string | null;
  school: { id: string; code: string; name: string };
  exam: {
    id: string;
    title: string;
    instructions: string | null;
    subject: string;
    duration_minutes: number;
    opens_at: string;
    closes_at: string;
    max_attempts: number;
    shuffle_questions: boolean;
    shuffle_options: boolean;
    results_release: string;
    instant_scores: boolean;
    total_marks: number;
  };
  paper: PackageItem[];
  passages: Record<string, { title: string; body: string }>;
  students: PackageStudent[];
  code_iterations: number;
  codes_batch: number;
  /** Only for instant-score exams, encrypted under the school's offline key. */
  answer_key: EncryptedBlob | null;
}

export class PackageError extends Error {}

/** The package inside a signed envelope, once its signature and school are checked. */
export function openPackage(
  envelope: unknown,
  trust: { signingPublicKey: string; schoolId: string },
): { envelope: Envelope; pkg: ExamPackage } {
  if (!isEnvelope(envelope) || envelope.format !== PACKAGE_FORMAT) {
    throw new PackageError("That isn't an exam package from Intelligent CBT.");
  }
  if (!verifyEnvelope(envelope, trust.signingPublicKey)) {
    throw new PackageError(
      "This exam package's signature doesn't match the school's server. It was changed, damaged, or comes from another server.",
    );
  }
  let pkg: ExamPackage;
  try {
    pkg = JSON.parse(envelope.body) as ExamPackage;
  } catch {
    throw new PackageError("This exam package couldn't be read.");
  }
  if (!pkg.school || pkg.school.id !== trust.schoolId) {
    throw new PackageError("This exam package is for another school.");
  }
  if (!pkg.exam?.id || !Array.isArray(pkg.paper) || !Array.isArray(pkg.students)) {
    throw new PackageError("This exam package is incomplete.");
  }
  return { envelope, pkg };
}
