import { test } from "node:test";
import assert from "node:assert/strict";
import { greet } from "../src/greet.mjs";

test("greet returns Hello, name", () => {
  assert.equal(greet("Ada"), "Hello, Ada");
});
