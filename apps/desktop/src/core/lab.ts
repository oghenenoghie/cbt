/**
 * Everything a lab computer does (ADR 0007, decision 9), without Electron: registering, keeping
 * exam packages, the exam room (sign-in, sitting, handing in), and sending results. The main process
 * wraps it (src/main/bridge.ts); tests drive it directly.
 *
 * Files under `dataDir`:
 *   device.json                  the registered computer (secrets sealed by the Vault)
 *   registration.json            a USB registration waiting for its setup file
 *   pin.json                     the lab PIN's hash
 *   exams.json                   which package is current for each exam, and whether it's offered
 *   packages/<package>.json      signed packages as received (checked again on every load)
 *   attempts/<id>.json           an attempt's fixed facts (orders, times)
 *   attempts/<id>.events.jsonl   its answers, appended and flushed one by one
 *   attempts/<id>.finish.json    when and how it ended
 *   outbox/<submission>.json     sealed results not yet answered by the server
 *   sent/<submission>.json       results with the server's answer
 *   sync.json                    the last time results were sent
 */

import { randomInt, randomUUID } from "node:crypto";

import type {
  DeviceSummary,
  Finished,
  GivenAnswer,
  LabStatus,
  ResultStatus,
  RoomExam,
  RoomExamState,
  SignedIn,
  Sitting,
  StaffOverview,
  SyncReport,
} from "../shared/api.js";
import {
  codeMatches,
  decrypt,
  isEnvelope,
  newExchangeKeys,
  newSigningKeys,
  openSealed,
  seal,
  verifyEnvelope,
  type EncryptedBlob,
  type Envelope,
} from "./crypto.js";
import { appendLine, join, listFiles, moveFile, readJson, readLines, writeJson } from "./files.js";
import { CHOICE_TYPES, mark, type AnswerKey } from "./marking.js";
import { openPackage, PackageError, type ExamPackage, type PackageItem } from "./package.js";
import { hashPin, LabPin, PinError, validPin, PIN_RULE } from "./pin.js";
import { server, serverAddress, ServerError, type SubmissionResult } from "./server.js";

export const REQUEST_FORMAT = "cbt-device-request/1";
export const SETUP_FORMAT = "cbt-device-setup/1";
export const SUBMISSION_FORMAT = "cbt-offline-submission/1";
export const RESULTS_FORMAT = "cbt-offline-results/1";

/** Answers are taken this long after the time is up, for a save already on its way. */
const GRACE_MS = 10_000;
const SIGN_IN_TRIES = 5;
const SIGN_IN_LOCK_MS = 60_000;
const MAX_SHORT_ANSWER_CHARS = 500;
const MAX_ANSWER_CHARS = 20_000;
const MAX_EVENTS = 20_000;

/** Keeps this computer's secrets encrypted at rest (Electron's safeStorage in the app). */
export interface Vault {
  readonly encrypted: boolean;
  seal(text: string): string;
  open(sealed: string): string;
}

export const plainVault: Vault = { encrypted: false, seal: (text) => text, open: (text) => text };

/** A problem to show as it is: the message is written for the person at the computer. */
export class LabError extends Error {}

interface DeviceConfig {
  device_id: string;
  name: string;
  school: { id: string; code: string; name: string };
  method: "online" | "file";
  server: string | null;
  signing_public_key: string;
  public_key: string;
  /** Sealed by the Vault. */
  private_key: string;
  token: string | null;
  school_key: string;
  registered_at: string;
}

interface PendingRegistration {
  name: string;
  public_key: string;
  private_key: string;
  exchange_private: string;
  request: Envelope;
  request_saved: boolean;
  created_at: string;
}

interface ExamRecord {
  exam_id: string;
  package_id: string;
  source: "online" | "usb";
  received_at: string;
  /** False once the server stopped offering it (withdrawn): students can't start it. */
  offered: boolean;
}

interface AttemptMeta {
  attempt_id: string;
  submission_id: string;
  package_id: string;
  exam_id: string;
  candidate_id: string;
  started_at: string;
  ends_at: string;
  question_order: string[];
  option_orders: Record<string, string[]>;
}

interface AttemptEvent {
  sequence: number;
  item_id: string;
  selected_option_ids: string[];
  text: string | null;
  at: string;
}

interface AttemptFinish {
  ended_at: string;
  reason: "student" | "time_up";
}

interface OutboxEntry {
  submission_id: string;
  attempt_id: string;
  envelope: Envelope;
  exam_id: string;
  exam_title: string;
  candidate_id: string;
  student_name: string;
  finished_at: string;
  saved_to_usb_at: string | null;
}

interface SentEntry extends OutboxEntry {
  status: ResultStatus;
  reason: string | null;
  flags: string[];
  sent_at: string;
}

interface Current {
  exam_id: string;
  candidate_id: string;
  attempt_id: string | null;
}

function shuffle<T>(items: T[]): T[] {
  for (let i = items.length - 1; i > 0; i--) {
    const j = randomInt(i + 1);
    [items[i], items[j]] = [items[j] as T, items[i] as T];
  }
  return items;
}

/** A fresh question order and option orders, by the online rules (app/attempts/service.py). */
export function newOrders(pkg: ExamPackage): {
  questionOrder: string[];
  optionOrders: Record<string, string[]>;
} {
  const items = [...pkg.paper].sort((a, b) => a.position - b.position);
  const blocks: string[][] = [];
  let lastBlock: number | null = null;
  for (const item of items) {
    if (item.block !== lastBlock) {
      blocks.push([]);
      lastBlock = item.block;
    }
    blocks[blocks.length - 1]?.push(item.item_id);
  }
  if (pkg.exam.shuffle_questions) shuffle(blocks);
  const optionOrders: Record<string, string[]> = {};
  for (const item of items) {
    const ids = item.options.map((o) => o.id);
    if (pkg.exam.shuffle_options && (item.type === "mcq_single" || item.type === "mcq_multiple"))
      shuffle(ids);
    optionOrders[item.item_id] = ids;
  }
  return { questionOrder: blocks.flat(), optionOrders };
}

/** The answer to keep for a question, by the server's rules (`checked_answer`), or why not. */
export function checkedAnswer(item: PackageItem, given: GivenAnswer): GivenAnswer {
  if ((CHOICE_TYPES as readonly string[]).includes(item.type)) {
    if (given.text !== null && given.text.trim()) throw new LabError("Choose an option for this question.");
    const chosen = [...new Set(given.selected)];
    const ids = item.options.map((o) => o.id);
    if (chosen.some((id) => !ids.includes(id)))
      throw new LabError("That isn't one of this question's options.");
    if (item.type !== "mcq_multiple" && chosen.length > 1) throw new LabError("Choose one option.");
    return { selected: chosen, text: null };
  }
  if (given.selected.length) throw new LabError("Type your answer for this question.");
  const text = given.text !== null && given.text.trim() ? given.text : null;
  const limit = item.type === "essay" ? MAX_ANSWER_CHARS : MAX_SHORT_ANSWER_CHARS;
  if (text !== null && text.length > limit)
    throw new LabError(`Keep this answer to ${limit} characters or fewer.`);
  return { selected: [], text };
}

export class Lab {
  readonly pin: LabPin;
  private current: Current | null = null;
  private signInFailures = new Map<string, { count: number; until: number }>();

  constructor(
    readonly dataDir: string,
    private readonly vault: Vault = plainVault,
    readonly now: () => Date = () => new Date(),
  ) {
    this.pin = new LabPin(join(dataDir, "pin.json"), now);
  }

  // --- Files ------------------------------------------------------------------------------------

  private path(...parts: string[]): string {
    return join(this.dataDir, ...parts);
  }

  private device(): DeviceConfig | null {
    return readJson<DeviceConfig>(this.path("device.json"));
  }

  private requireDevice(): DeviceConfig {
    const device = this.device();
    if (!device) throw new LabError("This computer isn't registered with a school yet.");
    return device;
  }

  private examIndex(): Record<string, ExamRecord> {
    return readJson<Record<string, ExamRecord>>(this.path("exams.json")) ?? {};
  }

  private saveExamIndex(index: Record<string, ExamRecord>): void {
    writeJson(this.path("exams.json"), index);
  }

  /** A stored package, checked again: a file changed on disk is refused. */
  private loadPackage(packageId: string): ExamPackage {
    const device = this.requireDevice();
    const envelope = readJson<Envelope>(this.path("packages", `${packageId}.json`));
    if (!envelope) throw new LabError("This exam's package is missing from the computer. Download it again.");
    try {
      return openPackage(envelope, {
        signingPublicKey: device.signing_public_key,
        schoolId: device.school.id,
      }).pkg;
    } catch (error) {
      throw new LabError((error as Error).message);
    }
  }

  private attemptMetas(): AttemptMeta[] {
    return listFiles(this.path("attempts"))
      .filter((name) => !name.endsWith(".finish.json"))
      .map((name) => readJson<AttemptMeta>(this.path("attempts", name)))
      .filter((meta): meta is AttemptMeta => meta !== null);
  }

  private finishOf(attemptId: string): AttemptFinish | null {
    return readJson<AttemptFinish>(this.path("attempts", `${attemptId}.finish.json`));
  }

  private events(attemptId: string): AttemptEvent[] {
    return readLines<AttemptEvent>(this.path("attempts", `${attemptId}.events.jsonl`));
  }

  private outbox(): OutboxEntry[] {
    return listFiles(this.path("outbox"))
      .map((name) => readJson<OutboxEntry>(this.path("outbox", name)))
      .filter((entry): entry is OutboxEntry => entry !== null);
  }

  private sent(): SentEntry[] {
    return listFiles(this.path("sent"))
      .map((name) => readJson<SentEntry>(this.path("sent", name)))
      .filter((entry): entry is SentEntry => entry !== null);
  }

  // --- Status and registration ------------------------------------------------------------------

  summary(): DeviceSummary | null {
    const device = this.device();
    if (!device) return null;
    return {
      name: device.name,
      school: { code: device.school.code, name: device.school.name },
      method: device.method,
      server: device.server,
      registered_at: device.registered_at,
    };
  }

  status(): Omit<LabStatus, "locked" | "staff"> {
    const pending = readJson<PendingRegistration>(this.path("registration.json"));
    return {
      registered: this.device() !== null,
      pending_file_registration: pending
        ? { name: pending.name, request_saved: pending.request_saved }
        : null,
      device: this.summary(),
      secure_storage: this.vault.encrypted,
    };
  }

  private refuseIfRegistered(): void {
    if (this.device()) throw new LabError("This computer is already registered.");
  }

  async registerOnline(input: {
    server: string;
    school_code: string;
    registration_code: string;
    name: string;
    pin: string;
  }): Promise<void> {
    this.refuseIfRegistered();
    if (!validPin(input.pin)) throw new LabError(PIN_RULE);
    const name = input.name.trim();
    if (!name) throw new LabError("Give this computer a name, such as “Lab A, PC 4”.");
    let address: string;
    try {
      address = serverAddress(input.server);
    } catch (error) {
      throw new LabError((error as Error).message);
    }
    const keys = newSigningKeys();
    const pin = await hashPin(input.pin);
    let registered;
    try {
      registered = await server.register(address, {
        school_code: input.school_code.trim(),
        registration_code: input.registration_code.trim(),
        name,
        public_key: keys.publicKey,
      });
    } catch (error) {
      throw new LabError((error as Error).message);
    }
    this.pin.save(pin);
    const device: DeviceConfig = {
      device_id: registered.device_id,
      name,
      school: registered.school,
      method: "online",
      server: address,
      signing_public_key: registered.signing_public_key,
      public_key: keys.publicKey,
      private_key: this.vault.seal(keys.privateKey),
      token: this.vault.seal(registered.device_token),
      school_key: this.vault.seal(registered.school_key),
      registered_at: this.now().toISOString(),
    };
    writeJson(this.path("device.json"), device);
  }

  /** Step 1 of registering by USB: keys, the lab PIN, and the request file to take to an admin. */
  async startFileRegistration(input: { name: string; pin: string }): Promise<void> {
    this.refuseIfRegistered();
    if (!validPin(input.pin)) throw new LabError(PIN_RULE);
    const name = input.name.trim();
    if (!name) throw new LabError("Give this computer a name, such as “Lab A, PC 4”.");
    const keys = newSigningKeys();
    const exchange = newExchangeKeys();
    const request = seal(
      REQUEST_FORMAT,
      { name, public_key: keys.publicKey, exchange_key: exchange.publicKey },
      keys.privateKey,
    );
    this.pin.save(await hashPin(input.pin));
    const pending: PendingRegistration = {
      name,
      public_key: keys.publicKey,
      private_key: this.vault.seal(keys.privateKey),
      exchange_private: this.vault.seal(exchange.privateKey),
      request,
      request_saved: false,
      created_at: this.now().toISOString(),
    };
    writeJson(this.path("registration.json"), pending);
  }

  /** The request file's contents, to save to a USB stick. */
  registrationRequest(): Envelope {
    const pending = readJson<PendingRegistration>(this.path("registration.json"));
    if (!pending) throw new LabError("Start registering by USB first.");
    return pending.request;
  }

  markRequestSaved(): void {
    const pending = readJson<PendingRegistration>(this.path("registration.json"));
    if (pending) writeJson(this.path("registration.json"), { ...pending, request_saved: true });
  }

  /** Step 2: the setup file the admin got back from the web app. */
  finishFileRegistration(data: unknown): void {
    this.refuseIfRegistered();
    const pending = readJson<PendingRegistration>(this.path("registration.json"));
    if (!pending) throw new LabError("Start registering by USB first.");
    if (!isEnvelope(data) || data.format !== SETUP_FORMAT) {
      throw new LabError(
        "That isn't a setup file. In the web app, register this computer's request file to get one.",
      );
    }
    let body: {
      device_id: string;
      name: string;
      school: { id: string; code: string; name: string };
      signing_public_key: string;
      school_key: EncryptedBlob;
    };
    try {
      body = JSON.parse(data.body);
    } catch {
      throw new LabError("That setup file couldn't be read.");
    }
    // The signing key arrives in the file itself: trusted on first use, as an admin brought it.
    if (!body.signing_public_key || !verifyEnvelope(data, body.signing_public_key)) {
      throw new LabError("That setup file's signature doesn't match: it may be damaged.");
    }
    let schoolKey: string;
    try {
      const opened = openSealed(
        body.school_key,
        this.vault.open(pending.exchange_private),
        body.device_id,
      ) as {
        key: string;
      };
      schoolKey = opened.key;
    } catch {
      throw new LabError("That setup file was made for another computer's request.");
    }
    const device: DeviceConfig = {
      device_id: body.device_id,
      name: body.name || pending.name,
      school: body.school,
      method: "file",
      server: null,
      signing_public_key: body.signing_public_key,
      public_key: pending.public_key,
      private_key: pending.private_key,
      token: null,
      school_key: this.vault.seal(schoolKey),
      registered_at: this.now().toISOString(),
    };
    writeJson(this.path("device.json"), device);
    moveFile(this.path("registration.json"), this.path("registration.done.json"));
  }

  cancelFileRegistration(): void {
    if (this.device()) return;
    moveFile(this.path("registration.json"), this.path("registration.cancelled.json"));
  }

  // --- Packages ---------------------------------------------------------------------------------

  private storePackage(envelope: unknown, source: "online" | "usb"): ExamPackage {
    const device = this.requireDevice();
    let opened;
    try {
      opened = openPackage(envelope, {
        signingPublicKey: device.signing_public_key,
        schoolId: device.school.id,
      });
    } catch (error) {
      throw new LabError((error as PackageError).message);
    }
    const { pkg } = opened;
    const index = this.examIndex();
    const existing = index[pkg.exam.id];
    if (existing && existing.package_id !== pkg.package_id) {
      const old = this.loadPackage(existing.package_id);
      if (
        old.codes_batch > pkg.codes_batch ||
        (old.codes_batch === pkg.codes_batch && old.issued_at > pkg.issued_at)
      ) {
        throw new LabError("This computer already has a newer package for this exam.");
      }
    }
    writeJson(this.path("packages", `${pkg.package_id}.json`), opened.envelope);
    index[pkg.exam.id] = {
      exam_id: pkg.exam.id,
      package_id: pkg.package_id,
      source,
      received_at: this.now().toISOString(),
      offered: true,
    };
    this.saveExamIndex(index);
    return pkg;
  }

  /** A package from a USB stick (saved for USB in the web app). */
  loadPackageFile(data: unknown): { title: string } {
    return { title: this.storePackage(data, "usb").exam.title };
  }

  private state(pkg: ExamPackage, record: ExamRecord, now = this.now()): RoomExamState {
    if (!record.offered) return "withdrawn";
    if (now < new Date(pkg.exam.opens_at)) return "upcoming";
    if (now >= new Date(pkg.exam.closes_at)) return "closed";
    return "open";
  }

  private roomExam(pkg: ExamPackage, record: ExamRecord): RoomExam {
    return {
      exam_id: pkg.exam.id,
      title: pkg.exam.title,
      subject: pkg.exam.subject,
      opens_at: pkg.exam.opens_at,
      closes_at: pkg.exam.closes_at,
      duration_minutes: pkg.exam.duration_minutes,
      question_count: pkg.paper.length,
      total_marks: pkg.exam.total_marks,
      instant_scores: pkg.exam.instant_scores,
      state: this.state(pkg, record),
    };
  }

  // --- The exam room ----------------------------------------------------------------------------

  /** Exams students can see: open now, then later today. */
  roomExams(): RoomExam[] {
    const out: RoomExam[] = [];
    for (const record of Object.values(this.examIndex())) {
      try {
        const exam = this.roomExam(this.loadPackage(record.package_id), record);
        if (exam.state === "open" || exam.state === "upcoming") out.push(exam);
      } catch {
        // A package that fails its check is shown to staff, never to students.
      }
    }
    return out.sort((a, b) => a.opens_at.localeCompare(b.opens_at) || a.title.localeCompare(b.title));
  }

  private finishedLocally(examId: string, candidateId: string, since: string | null): number {
    const sentBySubmission = new Map(this.sent().map((s) => [s.submission_id, s]));
    return this.attemptMetas().filter((meta) => {
      if (meta.exam_id !== examId || meta.candidate_id !== candidateId || !this.finishOf(meta.attempt_id)) {
        return false;
      }
      // Attempts the server had already accepted when the package was received are in its count.
      const sent = sentBySubmission.get(meta.submission_id);
      return !(sent && sent.status === "accepted" && since && sent.sent_at < since);
    }).length;
  }

  async signIn(input: { exam_id: string; username: string; code: string }): Promise<SignedIn> {
    const record = this.examIndex()[input.exam_id];
    if (!record) throw new LabError("That exam isn't on this computer.");
    const pkg = this.loadPackage(record.package_id);
    const state = this.state(pkg, record);
    if (state === "withdrawn") throw new LabError("This exam was withdrawn. Ask your invigilator.");
    if (state === "upcoming") throw new LabError("This exam hasn't opened yet.");
    if (state === "closed") throw new LabError("This exam has closed.");

    const username = input.username.trim().toLowerCase();
    const key = `${input.exam_id}:${username}`;
    const failures = this.signInFailures.get(key);
    if (failures && failures.until > Date.now()) {
      throw new LabError("Too many wrong codes. Wait a minute, or ask your invigilator.");
    }
    const student = pkg.students.find((s) => s.username?.toLowerCase() === username);
    const matches = Boolean(student?.code) && (await codeMatches(input.code, student!.code!));
    if (!student || !matches) {
      const count = (failures?.count ?? 0) + 1;
      this.signInFailures.set(key, {
        count: count >= SIGN_IN_TRIES ? 0 : count,
        until: count >= SIGN_IN_TRIES ? Date.now() + SIGN_IN_LOCK_MS : 0,
      });
      throw new LabError(
        student && !student.code
          ? "You don't have an exam code for this exam yet. Ask your invigilator."
          : "That username and exam code don't match. Check your slip and try again.",
      );
    }
    this.signInFailures.delete(key);

    // An attempt whose time ran out (the computer was off, or the window closed) is handed in now.
    this.recover();
    const unfinished = this.attemptMetas().find(
      (m) =>
        m.exam_id === pkg.exam.id && m.candidate_id === student.candidate_id && !this.finishOf(m.attempt_id),
    );
    const used =
      student.attempts_used + this.finishedLocally(pkg.exam.id, student.candidate_id, record.received_at);
    const left = Math.max(0, pkg.exam.max_attempts - used);
    if (!unfinished && left === 0) {
      throw new LabError(
        pkg.exam.max_attempts === 1
          ? "You've already sat this exam."
          : `You've used all ${pkg.exam.max_attempts} attempts at this exam.`,
      );
    }
    this.current = {
      exam_id: pkg.exam.id,
      candidate_id: student.candidate_id,
      attempt_id: unfinished?.attempt_id ?? null,
    };
    return {
      exam: {
        ...this.roomExam(pkg, record),
        instructions: pkg.exam.instructions,
        max_attempts: pkg.exam.max_attempts,
      },
      student: { name: student.name, class_name: student.class_name, username: student.username ?? username },
      resume: Boolean(unfinished),
      attempts_left: left,
    };
  }

  signOut(): void {
    this.current = null;
  }

  /** Start the signed-in student's attempt, or carry on with the one already started. */
  begin(): Sitting {
    const current = this.current;
    if (!current) throw new LabError("Sign in first.");
    if (!current.attempt_id) {
      const record = this.examIndex()[current.exam_id];
      if (!record) throw new LabError("That exam isn't on this computer.");
      const pkg = this.loadPackage(record.package_id);
      const now = this.now();
      if (this.state(pkg, record, now) !== "open") throw new LabError("This exam isn't open now.");
      const { questionOrder, optionOrders } = newOrders(pkg);
      const ends = Math.min(
        now.getTime() + pkg.exam.duration_minutes * 60_000,
        new Date(pkg.exam.closes_at).getTime(),
      );
      const meta: AttemptMeta = {
        attempt_id: randomUUID(),
        submission_id: randomUUID(),
        package_id: pkg.package_id,
        exam_id: pkg.exam.id,
        candidate_id: current.candidate_id,
        started_at: now.toISOString(),
        ends_at: new Date(ends).toISOString(),
        question_order: questionOrder,
        option_orders: optionOrders,
      };
      writeJson(this.path("attempts", `${meta.attempt_id}.json`), meta);
      current.attempt_id = meta.attempt_id;
    }
    return this.sitting();
  }

  private currentAttempt(): { meta: AttemptMeta; pkg: ExamPackage } {
    const attemptId = this.current?.attempt_id;
    if (!attemptId) throw new LabError("No exam is in progress.");
    const meta = readJson<AttemptMeta>(this.path("attempts", `${attemptId}.json`));
    if (!meta) throw new LabError("This attempt is missing from the computer.");
    return { meta, pkg: this.loadPackage(meta.package_id) };
  }

  private latest(attemptId: string): Record<string, GivenAnswer> {
    const answers: Record<string, GivenAnswer> = {};
    for (const event of this.events(attemptId)) {
      answers[event.item_id] = { selected: event.selected_option_ids, text: event.text };
    }
    return answers;
  }

  sitting(): Sitting {
    const { meta, pkg } = this.currentAttempt();
    if (this.finishOf(meta.attempt_id)) throw new LabError("This attempt has been handed in.");
    const items = new Map(pkg.paper.map((item) => [item.item_id, item]));
    const student = pkg.students.find((s) => s.candidate_id === meta.candidate_id);
    return {
      attempt_id: meta.attempt_id,
      exam_title: pkg.exam.title,
      subject: pkg.exam.subject,
      student_name: student?.name ?? "",
      ends_at: meta.ends_at,
      seconds_left: Math.max(0, Math.floor((new Date(meta.ends_at).getTime() - this.now().getTime()) / 1000)),
      questions: meta.question_order.map((itemId, index) => {
        const item = items.get(itemId) as PackageItem;
        const options = new Map(item.options.map((o) => [o.id, o]));
        return {
          item_id: item.item_id,
          number: index + 1,
          type: item.type,
          stem: item.stem,
          options: (meta.option_orders[itemId] ?? []).map((id) => options.get(id)!).filter(Boolean),
          marks: item.marks,
          passage: item.passage_id ? (pkg.passages[item.passage_id] ?? null) : null,
        };
      }),
      answers: this.latest(meta.attempt_id),
    };
  }

  /** Save one answer, flushed to disk before this returns. */
  answer(input: { item_id: string; selected: string[]; text: string | null }): { saved_at: string } {
    const { meta, pkg } = this.currentAttempt();
    if (this.finishOf(meta.attempt_id)) throw new LabError("This attempt has been handed in.");
    const now = this.now();
    if (now.getTime() > new Date(meta.ends_at).getTime() + GRACE_MS) {
      throw new LabError("Time is up. Your answers up to now are kept.");
    }
    const item = pkg.paper.find((i) => i.item_id === input.item_id);
    if (!item) throw new LabError("That question isn't on this exam.");
    const answer = checkedAnswer(item, { selected: input.selected ?? [], text: input.text ?? null });
    const events = this.events(meta.attempt_id);
    if (events.length >= MAX_EVENTS) throw new LabError("This attempt can't take more changes. Hand it in.");
    const event: AttemptEvent = {
      sequence: (events[events.length - 1]?.sequence ?? 0) + 1,
      item_id: item.item_id,
      selected_option_ids: answer.selected,
      text: answer.text,
      at: now.toISOString(),
    };
    appendLine(this.path("attempts", `${meta.attempt_id}.events.jsonl`), event);
    return { saved_at: event.at };
  }

  /** Hand in the current attempt: "time_up" once its time has run out, otherwise the student's. */
  handIn(): Finished {
    const { meta, pkg } = this.currentAttempt();
    const now = this.now();
    const timeUp = now.getTime() >= new Date(meta.ends_at).getTime();
    const finished = this.finish(
      meta,
      pkg,
      timeUp ? "time_up" : "student",
      timeUp ? meta.ends_at : now.toISOString(),
    );
    this.current = null;
    return finished;
  }

  private finish(
    meta: AttemptMeta,
    pkg: ExamPackage,
    reason: "student" | "time_up",
    endedAt: string,
  ): Finished {
    const device = this.requireDevice();
    const existing = this.finishOf(meta.attempt_id);
    const finish = existing ?? { ended_at: endedAt, reason };
    if (!existing) writeJson(this.path("attempts", `${meta.attempt_id}.finish.json`), finish);
    const events = this.events(meta.attempt_id);
    const student = pkg.students.find((s) => s.candidate_id === meta.candidate_id);
    const body = {
      submission_id: meta.submission_id,
      package_id: meta.package_id,
      exam_id: meta.exam_id,
      candidate_id: meta.candidate_id,
      device_id: device.device_id,
      started_at: meta.started_at,
      ended_at: finish.ended_at,
      submitted_reason: finish.reason,
      question_order: meta.question_order,
      option_orders: meta.option_orders,
      events: events.map((e) => ({
        sequence: e.sequence,
        item_id: e.item_id,
        selected_option_ids: e.selected_option_ids,
        text: e.text,
        at: e.at,
      })),
    };
    const sealed = seal(SUBMISSION_FORMAT, body, this.vault.open(device.private_key));
    const already =
      readJson(this.path("outbox", `${meta.submission_id}.json`)) ??
      readJson(this.path("sent", `${meta.submission_id}.json`));
    if (!already) {
      const entry: OutboxEntry = {
        submission_id: meta.submission_id,
        attempt_id: meta.attempt_id,
        envelope: sealed,
        exam_id: meta.exam_id,
        exam_title: pkg.exam.title,
        candidate_id: meta.candidate_id,
        student_name: student?.name ?? "",
        finished_at: finish.ended_at,
        saved_to_usb_at: null,
      };
      writeJson(this.path("outbox", `${meta.submission_id}.json`), entry);
    }
    const answers = this.latest(meta.attempt_id);
    const answered = Object.values(answers).filter(
      (a) => a.selected.length > 0 || Boolean(a.text?.trim()),
    ).length;
    const out: Finished = {
      student_name: student?.name ?? "",
      exam_title: pkg.exam.title,
      reason: finish.reason,
      answered,
      question_count: pkg.paper.length,
      score: null,
      max_score: null,
      to_mark: 0,
    };
    if (pkg.exam.instant_scores && pkg.answer_key) {
      try {
        const keys = decrypt(pkg.answer_key, this.vault.open(device.school_key), pkg.package_id) as Record<
          string,
          AnswerKey
        >;
        let score = 0;
        let toMark = 0;
        for (const item of pkg.paper) {
          const key = keys[item.item_id];
          if (!key) continue;
          const marked = mark(key, item.marks, answers[item.item_id] ?? { selected: [], text: null });
          score += marked.score;
          if (marked.needsMarking) toMark += 1;
        }
        Object.assign(out, { score, max_score: pkg.exam.total_marks, to_mark: toMark });
      } catch {
        // No instant score then; the server still marks the answers.
      }
    }
    return out;
  }

  /**
   * After a restart: finish attempts whose time ran out while the computer was off, and make sure
   * every finished attempt has its sealed result waiting to be sent.
   */
  recover(): number {
    if (!this.device()) return 0;
    let finished = 0;
    const now = this.now().getTime();
    for (const meta of this.attemptMetas()) {
      const done = this.finishOf(meta.attempt_id);
      const overdue = now > new Date(meta.ends_at).getTime() + GRACE_MS;
      const missing =
        done &&
        !readJson(this.path("outbox", `${meta.submission_id}.json`)) &&
        !readJson(this.path("sent", `${meta.submission_id}.json`));
      if ((!done && overdue) || missing) {
        try {
          this.finish(meta, this.loadPackage(meta.package_id), "time_up", meta.ends_at);
          finished += 1;
        } catch {
          // Its package is gone or damaged: staff see it as a problem on the staff side.
        }
      }
    }
    return finished;
  }

  // --- Sending results ----------------------------------------------------------------------------

  private record(entry: OutboxEntry, outcome: Pick<SentEntry, "status" | "reason" | "flags">): void {
    const sent: SentEntry = { ...entry, ...outcome, sent_at: this.now().toISOString() };
    writeJson(this.path("sent", `${entry.submission_id}.json`), sent);
    moveFile(
      this.path("outbox", `${entry.submission_id}.json`),
      this.path("sent", `${entry.submission_id}.outbox`),
    );
  }

  private report(ok: boolean, message: string): SyncReport {
    const report = { at: this.now().toISOString(), ok, message };
    writeJson(this.path("sync.json"), report);
    return report;
  }

  /**
   * Send waiting results, then fetch exams that are new or have new codes, and notice exams the
   * server no longer offers. Only for computers registered over the internet.
   */
  async sync(): Promise<SyncReport> {
    const device = this.requireDevice();
    if (device.method !== "online" || !device.server || !device.token) {
      throw new LabError("This computer was registered by USB: save results to a USB stick instead.");
    }
    const token = this.vault.open(device.token);
    let sent = 0;
    try {
      for (const entry of this.outbox()) {
        try {
          const result: SubmissionResult = await server.submit(device.server, token, entry.envelope);
          this.record(entry, { status: result.status, reason: result.reason, flags: result.flags });
        } catch (error) {
          if (
            !(error instanceof ServerError) ||
            error.unreachable ||
            error.status === 401 ||
            error.status >= 500
          ) {
            throw error;
          }
          // Refused outright (a damaged result, a student not at the school): kept for staff.
          this.record(entry, { status: "refused", reason: error.message, flags: [] });
        }
        sent += 1;
      }
      const offered = (await server.exams(device.server, token)).exams;
      const index = this.examIndex();
      let downloaded = 0;
      for (const exam of offered) {
        if (!exam.codes_ready) continue;
        const record = index[exam.id];
        const pkg = record ? this.tryLoad(record.package_id) : null;
        if (!record || !pkg || pkg.codes_batch < exam.codes_batch || !record.offered) {
          this.storePackage(await server.package(device.server, token, exam.id), "online");
          downloaded += 1;
        }
      }
      const offeredIds = new Set(offered.map((e) => e.id));
      const latest = this.examIndex();
      for (const record of Object.values(latest)) {
        const pkg = this.tryLoad(record.package_id);
        if (pkg && !offeredIds.has(record.exam_id) && this.now() < new Date(pkg.exam.closes_at)) {
          record.offered = false;
        }
      }
      this.saveExamIndex(latest);
      const parts = [sent === 1 ? "1 result sent" : `${sent} results sent`];
      if (downloaded) parts.push(downloaded === 1 ? "1 exam downloaded" : `${downloaded} exams downloaded`);
      return this.report(true, `Up to date: ${parts.join(", ")}.`);
    } catch (error) {
      const message =
        error instanceof ServerError || error instanceof LabError ? error.message : "Sending results failed.";
      return this.report(false, sent ? `${sent} sent, then: ${message}` : message);
    }
  }

  private tryLoad(packageId: string): ExamPackage | null {
    try {
      return this.loadPackage(packageId);
    } catch {
      return null;
    }
  }

  /** Results for a USB stick: those not yet answered by the server, or every result. */
  resultsFile(scope: "unsent" | "all"): { data: unknown; count: number } {
    const waiting = this.outbox();
    const entries = scope === "all" ? [...waiting, ...this.sent()] : waiting;
    return {
      data: { format: RESULTS_FORMAT, submissions: entries.map((e) => e.envelope) },
      count: entries.length,
    };
  }

  markSavedToUsb(scope: "unsent" | "all"): void {
    const at = this.now().toISOString();
    for (const entry of this.outbox()) {
      writeJson(this.path("outbox", `${entry.submission_id}.json`), { ...entry, saved_to_usb_at: at });
    }
    if (scope === "all") {
      for (const entry of this.sent()) {
        writeJson(this.path("sent", `${entry.submission_id}.json`), { ...entry, saved_to_usb_at: at });
      }
    }
  }

  // --- The staff side -------------------------------------------------------------------------------

  overview(): StaffOverview {
    const device = this.summary();
    if (!device) throw new LabError("This computer isn't registered with a school yet.");
    const metas = this.attemptMetas();
    const exams = Object.values(this.examIndex()).flatMap((record) => {
      const pkg = this.tryLoad(record.package_id);
      if (!pkg) return [];
      const mine = metas.filter((m) => m.exam_id === record.exam_id);
      const finished = mine.filter((m) => this.finishOf(m.attempt_id)).length;
      return [
        {
          exam_id: record.exam_id,
          title: pkg.exam.title,
          subject: pkg.exam.subject,
          opens_at: pkg.exam.opens_at,
          closes_at: pkg.exam.closes_at,
          state: this.state(pkg, record),
          source: record.source,
          received_at: record.received_at,
          students: pkg.students.length,
          in_progress: mine.length - finished,
          finished,
        },
      ];
    });
    exams.sort((a, b) => b.opens_at.localeCompare(a.opens_at));
    const results = [
      ...this.outbox().map((e) => ({
        ...e,
        status: "waiting" as ResultStatus,
        reason: null,
        flags: [],
        sent_at: null,
      })),
      ...this.sent(),
    ]
      .map((e) => ({
        submission_id: e.submission_id,
        exam_title: e.exam_title,
        student_name: e.student_name,
        finished_at: e.finished_at,
        status: e.status,
        reason: e.reason,
        flags: e.flags,
        saved_to_usb_at: e.saved_to_usb_at,
        sent_at: e.sent_at,
      }))
      .sort((a, b) => b.finished_at.localeCompare(a.finished_at));
    return { device, exams, results, last_sync: readJson<SyncReport>(this.path("sync.json")) };
  }

  async changePin(current: string, next: string): Promise<void> {
    try {
      await this.pin.change(current, next);
    } catch (error) {
      throw new LabError((error as PinError).message);
    }
  }
}
