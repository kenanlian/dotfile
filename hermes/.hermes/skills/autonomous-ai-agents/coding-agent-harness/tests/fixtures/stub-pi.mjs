#!/usr/bin/env node
import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";

if (process.argv.includes("--version")) {
  process.stdout.write("0.85.1-stub\n");
  process.exit(0);
}

const dumpPath = process.env.PI_STUB_DUMP;
if (dumpPath) {
  writeFileSync(
    dumpPath,
    `${JSON.stringify({ argv: process.argv.slice(2) })}\n`,
    "utf8",
  );
}

if (process.env.PI_STUB_WRITE_RELPATH) {
  const target = join(process.cwd(), process.env.PI_STUB_WRITE_RELPATH);
  mkdirSync(dirname(target), { recursive: true });
  writeFileSync(target, process.env.PI_STUB_WRITE_CONTENTS ?? "stub-write\n");
}

if (process.env.PI_STUB_SLEEP_MS) {
  const started = Date.now();
  while (Date.now() - started < Number(process.env.PI_STUB_SLEEP_MS)) {
    /* busy wait so the relay watchdog can fire */
  }
}

if (process.env.PI_STUB_EXIT) {
  process.exit(Number(process.env.PI_STUB_EXIT));
}

const sessionId = process.env.PI_STUB_SESSION ?? "stub-session-1";
if (process.env.PI_STUB_NO_SESSION) {
  /* exact-resume tests omit the session event so the relay cannot infer identity */
} else if (process.env.PI_STUB_SESSION_MISMATCH) {
  process.stdout.write(`${JSON.stringify({ type: "session", id: process.env.PI_STUB_SESSION_MISMATCH })}\n`);
} else {
  process.stdout.write(`${JSON.stringify({ type: "session", id: sessionId })}\n`);
}

const expected = process.env.PI_HARNESS_EXPECT_EXTENSIONS;
if (expected && !process.env.PI_STUB_NO_ATTESTATION) {
  process.stdout.write(`${JSON.stringify({
    type: "session_start",
    harnessAttestation: {
      version: "coding-agent.attestation.v1",
      expected: expected.split(",").filter(Boolean),
    },
  })}\n`);
}

const extraEvents = process.env.PI_STUB_EVENTS;
if (extraEvents) {
  const events = JSON.parse(extraEvents);
  if (!Array.isArray(events)) throw new Error("PI_STUB_EVENTS must be a JSON array");
  for (const event of events) {
    process.stdout.write(`${JSON.stringify(event)}\n`);
  }
}

const finalText = process.env.PI_STUB_FINAL ?? "stub final";
process.stdout.write(`${JSON.stringify({
  type: "message_end",
  message: {
    role: "assistant",
    provider: "stub",
    model: "stub-model",
    content: [{ type: "text", text: finalText }],
  },
})}\n`);
if (!process.env.PI_STUB_NO_SETTLED) {
  process.stdout.write(`${JSON.stringify({ type: "agent_settled" })}\n`);
}
process.exit(0);
