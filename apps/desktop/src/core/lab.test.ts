// The exam room and results, driven directly: a synthetic school's package signed with a test key,
// as the server would sign it. Server calls are covered by the end-to-end check against the API.
import assert from "node:assert/strict";
import { createCipheriv, pbkdf2Sync, randomBytes } from "node:crypto";
import { mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";

import { newSigningKeys, seal, verifyEnvelope, type Envelope } from "./crypto.js";
import {
  checkedAnswer,
  Lab,
  LabError,
  newOrders,
  plainVault,
  RESULTS_FORMAT,
  SUBMISSION_FORMAT,
} from "./lab.js";
import type { ExamPackage } from "./package.js";

const server = newSigningKeys();
const school = { id: "school-1", code: "demo", name: "Demo Secondary School" };

function codeHash(code: string) {
  const salt = randomBytes(16);
  return {
    salt: salt.toString("hex"),
    hash: pbkdf2Sync(code.replace("-", ""), salt, 1000, 32, "sha256").toString("hex"),
    iterations: 1000,
  };
}

function aPackage(clock: Date, overrides: Partial<ExamPackage["exam"]> = {}, batch = 1): ExamPackage {
  return {
    package_id: `pkg-${batch}-${randomBytes(3).toString("hex")}`,
    issued_at: clock.toISOString(),
    device_id: null,
    school,
    exam: {
      id: "exam-1",
      title: "Lab Test",
      instructions: "Answer every question.",
      subject: "Basic Science",
      duration_minutes: 30,
      opens_at: new Date(clock.getTime() - 5 * 60_000).toISOString(),
      closes_at: new Date(clock.getTime() + 120 * 60_000).toISOString(),
      max_attempts: 1,
      shuffle_questions: true,
      shuffle_options: true,
      results_release: "teacher",
      instant_scores: false,
      total_marks: 5,
      ...overrides,
    },
    paper: [
      {
        item_id: "q1",
        position: 1,
        block: 1,
        passage_id: null,
        type: "mcq_single",
        stem: "Which is alive?",
        options: [
          { id: "a", text: "A stone" },
          { id: "b", text: "A goat" },
          { id: "c", text: "A chair" },
        ],
        marks: 2,
      },
      {
        item_id: "q2",
        position: 2,
        block: 2,
        passage_id: "p1",
        type: "mcq_single",
        stem: "What falls as rain?",
        options: [
          { id: "a", text: "Water" },
          { id: "b", text: "Sand" },
        ],
        marks: 1,
      },
      {
        item_id: "q3",
        position: 3,
        block: 2,
        passage_id: "p1",
        type: "true_false",
        stem: "Clouds are water.",
        options: [
          { id: "true", text: "True" },
          { id: "false", text: "False" },
        ],
        marks: 1,
      },
      {
        item_id: "q4",
        position: 4,
        block: 3,
        passage_id: null,
        type: "short_answer",
        stem: "Name the gas plants take in.",
        options: [],
        marks: 1,
      },
    ],
    passages: { p1: { title: "The water cycle", body: "Water evaporates and falls as rain." } },
    students: [
      {
        candidate_id: "c-amy",
        username: "amy",
        name: "Amy Ade",
        class_name: "JSS1 A",
        attempts_used: 0,
        code: codeHash("K7QM-3XRP"),
      },
      {
        candidate_id: "c-ben",
        username: "ben",
        name: "Ben Bello",
        class_name: "JSS1 A",
        attempts_used: 1,
        code: codeHash("ABCD-EFGH"),
      },
      {
        candidate_id: "c-cara",
        username: "cara",
        name: "Cara Cole",
        class_name: "JSS1 A",
        attempts_used: 0,
        code: null,
      },
    ],
    code_iterations: 1000,
    codes_batch: batch,
    answer_key: null,
  };
}

/** A lab registered to the synthetic school, with a clock the test moves. */
function aLab() {
  const dir = mkdtempSync(join(tmpdir(), "lab-"));
  const keys = newSigningKeys();
  const clock = { now: new Date("2026-11-16T09:00:00Z") };
  writeFileSync(
    join(dir, "device.json"),
    JSON.stringify({
      device_id: "device-1",
      name: "Lab A, PC 1",
      school,
      method: "file",
      server: null,
      signing_public_key: server.publicKey,
      public_key: keys.publicKey,
      private_key: keys.privateKey,
      token: null,
      school_key: "unused",
      registered_at: clock.now.toISOString(),
    }),
  );
  const lab = new Lab(dir, plainVault, () => clock.now);
  return { lab, keys, clock, dir };
}

const signed = (pkg: ExamPackage): Envelope => seal("cbt-offline-package/1", pkg, server.privateKey);

test("orders keep passages together and true/false options fixed", () => {
  const pkg = aPackage(new Date());
  for (let i = 0; i < 20; i++) {
    const { questionOrder, optionOrders } = newOrders(pkg);
    assert.deepEqual([...questionOrder].sort(), ["q1", "q2", "q3", "q4"]);
    assert.equal(questionOrder.indexOf("q3"), questionOrder.indexOf("q2") + 1);
    assert.deepEqual(optionOrders.q3, ["true", "false"]);
    assert.deepEqual(optionOrders.q4, []);
    assert.deepEqual([...(optionOrders.q1 ?? [])].sort(), ["a", "b", "c"]);
  }
});

test("answers are checked by question type, as the server checks them", () => {
  const [q1, , , q4] = aPackage(new Date()).paper;
  assert.deepEqual(checkedAnswer(q1!, { selected: ["b", "b"], text: null }), { selected: ["b"], text: null });
  assert.throws(() => checkedAnswer(q1!, { selected: ["a", "b"], text: null }), /Choose one option/);
  assert.throws(() => checkedAnswer(q1!, { selected: ["z"], text: null }), /isn't one of/);
  assert.throws(() => checkedAnswer(q1!, { selected: [], text: "goat" }), /Choose an option/);
  assert.deepEqual(checkedAnswer(q4!, { selected: [], text: "   " }), { selected: [], text: null });
  assert.throws(() => checkedAnswer(q4!, { selected: [], text: "x".repeat(501) }), /500 characters/);
});

test("packages are checked: signature, school, and not older than the one held", () => {
  const { lab, clock } = aLab();
  const pkg = aPackage(clock.now);
  const forged = { ...signed(pkg), body: signed(pkg).body.replace("Lab Test", "Easy Test") };
  assert.throws(() => lab.loadPackageFile(forged), /signature doesn't match/);
  const otherSchool = aPackage(clock.now);
  otherSchool.school = { ...school, id: "school-2" };
  assert.throws(() => lab.loadPackageFile(signed(otherSchool)), /another school/);
  assert.throws(() => lab.loadPackageFile({ hello: "world" }), /isn't an exam package/);

  const newer = aPackage(clock.now, {}, 2);
  assert.equal(lab.loadPackageFile(signed(newer)).title, "Lab Test");
  assert.throws(() => lab.loadPackageFile(signed(pkg)), /newer package/);
  assert.deepEqual(
    lab.roomExams().map((e) => [e.title, e.state, e.question_count]),
    [["Lab Test", "open", 4]],
  );
});

test("students sign in with their code; wrong codes are throttled", async () => {
  const { lab, clock } = aLab();
  lab.loadPackageFile(signed(aPackage(clock.now)));
  const exam = { exam_id: "exam-1" };
  await assert.rejects(lab.signIn({ ...exam, username: "amy", code: "WRONG-CODE" }), /don't match/);
  await assert.rejects(lab.signIn({ ...exam, username: "nobody", code: "K7QM-3XRP" }), /don't match/);
  await assert.rejects(
    lab.signIn({ ...exam, username: "cara", code: "ANYT-HING" }),
    /don't have an exam code/,
  );
  await assert.rejects(lab.signIn({ ...exam, username: "ben", code: "ABCD-EFGH" }), /already sat this exam/);
  for (let i = 0; i < 4; i++) await assert.rejects(lab.signIn({ ...exam, username: "amy", code: "nope" }));
  await assert.rejects(lab.signIn({ ...exam, username: "amy", code: "K7QM-3XRP" }), /Too many wrong codes/);

  const { lab: other, clock: otherClock } = aLab();
  other.loadPackageFile(signed(aPackage(otherClock.now)));
  const signedIn = await other.signIn({ ...exam, username: " AMY ", code: "k7qm3xrp" });
  assert.equal(signedIn.student.name, "Amy Ade");
  assert.equal(signedIn.resume, false);
  assert.equal(signedIn.attempts_left, 1);
});

test("an attempt is saved answer by answer, survives a restart, and seals a signed result", async () => {
  const { lab, clock, dir, keys } = aLab();
  lab.loadPackageFile(signed(aPackage(clock.now)));
  await lab.signIn({ exam_id: "exam-1", username: "amy", code: "K7QM-3XRP" });
  const sitting = lab.begin();
  assert.equal(sitting.seconds_left, 30 * 60);
  // Updates wait until every student on this computer has handed in.
  assert.match(lab.overview().app.install_blocked ?? "", /hasn't handed in/);
  assert.equal(sitting.questions.find((q) => q.item_id === "q2")?.passage?.title, "The water cycle");
  lab.answer({ item_id: "q1", selected: ["a"], text: null });
  lab.answer({ item_id: "q1", selected: ["b"], text: null });
  lab.answer({ item_id: "q4", selected: [], text: "Carbon dioxide" });
  assert.throws(() => lab.answer({ item_id: "q9", selected: [], text: "x" }), LabError);

  // The computer restarts: a new Lab on the same folder, the student signs in again and carries on.
  clock.now = new Date(clock.now.getTime() + 10 * 60_000);
  const restarted = new Lab(dir, plainVault, () => clock.now);
  const again = await restarted.signIn({ exam_id: "exam-1", username: "amy", code: "K7QM-3XRP" });
  assert.equal(again.resume, true);
  const resumed = restarted.begin();
  assert.equal(resumed.attempt_id, sitting.attempt_id);
  assert.equal(resumed.seconds_left, 20 * 60);
  assert.deepEqual(resumed.answers.q1, { selected: ["b"], text: null });

  const finished = restarted.handIn();
  assert.equal(finished.reason, "student");
  assert.equal(restarted.overview().app.install_blocked, null);
  assert.equal(finished.answered, 2);
  assert.equal(finished.score, null);
  await assert.rejects(
    restarted.signIn({ exam_id: "exam-1", username: "amy", code: "K7QM-3XRP" }),
    /already sat/,
  );

  const file = restarted.resultsFile("unsent");
  assert.equal(file.count, 1);
  const data = file.data as { format: string; submissions: Envelope[] };
  assert.equal(data.format, RESULTS_FORMAT);
  const result = data.submissions[0]!;
  assert.equal(result.format, SUBMISSION_FORMAT);
  assert.equal(verifyEnvelope(result, keys.publicKey), true);
  const body = JSON.parse(result.body);
  assert.equal(body.candidate_id, "c-amy");
  assert.equal(body.device_id, "device-1");
  assert.equal(body.submitted_reason, "student");
  assert.deepEqual(
    body.events.map((e: { sequence: number; item_id: string }) => [e.sequence, e.item_id]),
    [
      [1, "q1"],
      [2, "q1"],
      [3, "q4"],
    ],
  );
  restarted.markSavedToUsb("unsent");
  assert.ok(restarted.overview().results[0]?.saved_to_usb_at);
});

test("time runs out while the computer is off: the attempt is handed in as time up", async () => {
  const { lab, clock, dir } = aLab();
  lab.loadPackageFile(signed(aPackage(clock.now)));
  await lab.signIn({ exam_id: "exam-1", username: "amy", code: "K7QM-3XRP" });
  const sitting = lab.begin();
  lab.answer({ item_id: "q1", selected: ["b"], text: null });

  clock.now = new Date(clock.now.getTime() + 45 * 60_000);
  const restarted = new Lab(dir, plainVault, () => clock.now);
  assert.equal(restarted.recover(), 1);
  const body = JSON.parse(
    (restarted.resultsFile("unsent").data as { submissions: Envelope[] }).submissions[0]!.body,
  );
  assert.equal(body.submitted_reason, "time_up");
  assert.equal(body.ended_at, sitting.ends_at);
  assert.equal(restarted.recover(), 0);
});

test("an attempt ends at closing time even if its duration is longer", async () => {
  const { lab, clock } = aLab();
  lab.loadPackageFile(
    signed(aPackage(clock.now, { closes_at: new Date(clock.now.getTime() + 10 * 60_000).toISOString() })),
  );
  await lab.signIn({ exam_id: "exam-1", username: "amy", code: "K7QM-3XRP" });
  assert.equal(lab.begin().seconds_left, 10 * 60);
  clock.now = new Date(clock.now.getTime() + 11 * 60_000);
  assert.throws(() => lab.answer({ item_id: "q1", selected: ["b"], text: null }), /Time is up/);
  assert.equal(lab.handIn().reason, "time_up");
});

test("upcoming and closed exams can't be started", async () => {
  const { lab, clock } = aLab();
  lab.loadPackageFile(
    signed(aPackage(clock.now, { opens_at: new Date(clock.now.getTime() + 3600_000).toISOString() })),
  );
  assert.equal(lab.roomExams()[0]?.state, "upcoming");
  await assert.rejects(
    lab.signIn({ exam_id: "exam-1", username: "amy", code: "K7QM-3XRP" }),
    /hasn't opened/,
  );
  clock.now = new Date(clock.now.getTime() + 24 * 3600_000);
  assert.deepEqual(lab.roomExams(), []);
  await assert.rejects(lab.signIn({ exam_id: "exam-1", username: "amy", code: "K7QM-3XRP" }), /has closed/);
});

test("instant scores: the key is opened with the school key and marked like the server", async () => {
  const { lab, clock, dir } = aLab();
  const schoolKey = randomBytes(32);
  const device = JSON.parse(readFileSync(join(dir, "device.json"), "utf8"));
  writeFileSync(
    join(dir, "device.json"),
    JSON.stringify({ ...device, school_key: schoolKey.toString("base64") }),
  );
  const pkg = aPackage(clock.now, { instant_scores: true, results_release: "immediate" });
  const nonce = randomBytes(12);
  const cipher = createCipheriv("aes-256-gcm", schoolKey, nonce);
  cipher.setAAD(Buffer.from(pkg.package_id));
  const keys = {
    q1: { type: "mcq_single", correct_option_ids: ["b"], answer_key: null },
    q2: { type: "mcq_single", correct_option_ids: ["a"], answer_key: null },
    q3: { type: "true_false", correct_option_ids: ["true"], answer_key: null },
    q4: {
      type: "short_answer",
      correct_option_ids: [],
      answer_key: { accepted_answers: ["Carbon dioxide", "CO2"] },
    },
  };
  const encrypted = Buffer.concat([cipher.update(JSON.stringify(keys)), cipher.final(), cipher.getAuthTag()]);
  pkg.answer_key = {
    alg: "A256GCM",
    nonce: nonce.toString("base64"),
    ciphertext: encrypted.toString("base64"),
  };
  lab.loadPackageFile(signed(pkg));

  await lab.signIn({ exam_id: "exam-1", username: "amy", code: "K7QM-3XRP" });
  lab.begin();
  lab.answer({ item_id: "q1", selected: ["b"], text: null });
  lab.answer({ item_id: "q3", selected: ["false"], text: null });
  lab.answer({ item_id: "q4", selected: [], text: " co2. " });
  const finished = lab.handIn();
  assert.deepEqual([finished.score, finished.max_score, finished.to_mark], [3, 5, 0]);
});

test("the lab PIN: digits only, and wrong PINs lock it", async () => {
  const { lab, clock } = aLab();
  const { hashPin } = await import("./pin.js");
  await assert.rejects(hashPin("12345"), /6 to 12 digits/);
  lab.pin.save(await hashPin("246810"));
  await lab.pin.check("246810");
  for (let i = 0; i < 4; i++) await assert.rejects(lab.pin.check("000000"), /^Error: Wrong PIN\.$|Wrong PIN/);
  await assert.rejects(lab.pin.check("000000"), /wait a minute/);
  await assert.rejects(lab.pin.check("246810"), /Try again in 60 seconds/);
  clock.now = new Date(clock.now.getTime() + 61_000);
  await lab.pin.check("246810");
  await lab.changePin("246810", "13579135");
  await assert.rejects(lab.pin.check("246810"), /Wrong PIN/);
  await lab.pin.check("13579135");
});
