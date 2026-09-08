#!/usr/bin/env node
import { writeFileSync } from "node:fs";

if (process.argv.includes("--version")) {
  process.stdout.write("0.85.1-stub\n");
  process.exit(0);
}

const dumpPath = process.env.PI_STUB_DUMP;
if (dumpPath) {
  writeFileSync(
    dumpPath,
    `${JSON.stringify({
      argv: process.argv.slice(2),
      planEnv: process.env.PI_AUTO_HANDOFF_PLAN_FILE ?? null,
      handoffEnv: process.env.PI_AUTO_HANDOFF_HANDOFF_DIR ?? null,
    })}\n`,
    "utf8",
  );
}

const sessionId = process.env.PI_STUB_SESSION ?? "stub-session-1";
process.stdout.write(`${JSON.stringify({ type: "session", id: sessionId })}\n`);
process.stdout.write(`${JSON.stringify({
  type: "message_end",
  message: {
    role: "assistant",
    provider: "stub",
    model: "stub-model",
    content: [{ type: "text", text: "stub final" }],
  },
})}\n`);
process.stdout.write(`${JSON.stringify({ type: "agent_settled" })}\n`);
process.exit(0);
