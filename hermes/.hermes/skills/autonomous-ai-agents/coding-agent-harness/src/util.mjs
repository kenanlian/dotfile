import { createHash } from "node:crypto";
import {
  closeSync,
  constants as fsConstants,
  existsSync,
  fsyncSync,
  lstatSync,
  mkdirSync,
  openSync,
  readFileSync,
  realpathSync,
  renameSync,
  statSync,
  writeFileSync,
} from "node:fs";
import { dirname, isAbsolute, join, relative, resolve, sep } from "node:path";

export function sha256Buffer(buffer) {
  return createHash("sha256").update(buffer).digest("hex");
}

export function sha256Text(text) {
  return sha256Buffer(Buffer.from(text, "utf8"));
}

export function sha256File(path) {
  return sha256Buffer(readFileSync(path));
}

export function canonicalJson(value) {
  return `${JSON.stringify(value, null, 2)}\n`;
}

export function isPathInside(child, parent) {
  const resolvedParent = resolve(parent);
  const resolvedChild = resolve(child);
  if (resolvedChild === resolvedParent) return true;
  const prefix = resolvedParent.endsWith(sep) ? resolvedParent : `${resolvedParent}${sep}`;
  return resolvedChild.startsWith(prefix);
}

export function nearestExistingPath(path) {
  let cursor = resolve(path);
  while (!existsSync(cursor)) {
    const parent = dirname(cursor);
    if (parent === cursor) return cursor;
    cursor = parent;
  }
  return cursor;
}

export function realpathIfExists(path) {
  if (!existsSync(path)) return null;
  return realpathSync(path);
}

export function assertRegularReadableFile(path) {
  const st = statSync(path);
  if (!st.isFile()) {
    const error = new Error(`not a regular file: ${path}`);
    error.code = "ENOTFILE";
    throw error;
  }
  return st;
}

export function atomicWriteFile(path, contents) {
  mkdirSync(dirname(path), { recursive: true });
  const temporary = `${path}.${process.pid}.tmp`;
  writeFileSync(temporary, contents);
  const fd = openSync(temporary, "r");
  try {
    fsyncSync(fd);
  } finally {
    closeSync(fd);
  }
  renameSync(temporary, path);
}

export function exclusiveWriteFile(path, contents) {
  mkdirSync(dirname(path), { recursive: true });
  const fd = openSync(path, fsConstants.O_CREAT | fsConstants.O_EXCL | fsConstants.O_WRONLY, 0o644);
  try {
    writeFileSync(fd, contents);
    fsyncSync(fd);
  } finally {
    closeSync(fd);
  }
}

export function toRepoRelative(repoRoot, absPath) {
  const rel = relative(repoRoot, absPath);
  return rel.split(sep).join("/");
}

export { dirname, isAbsolute, join, relative, resolve, sep };
