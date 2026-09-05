---
name: coding-agent-configuration
description: "Use when configuring coding-agent CLI roles globally."
version: 1.0.0
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [coding-agent, configuration, subagents, permissions, validation]
    related_skills: [opencode, codex, claude-code, development-orchestrator]
---

# Coding-Agent Configuration

Install, adapt, and verify reusable agent definitions, role prompts, and permission policies for coding-agent CLIs. Treat configuration as executable behavior: a file being present or a role appearing in a list is not proof that the host understood every field.

## Use This Skill When

- Promoting project-owned agent definitions into a CLI's global configuration.
- Installing reusable workers, explorers, reviewers, or other custom roles.
- Migrating definitions between host versions or configuration schemas.
- Diagnosing why a discovered agent does not have its intended model, tools, or permissions.
- Choosing between central JSON/JSONC configuration, per-agent Markdown definitions, or external prompt files.
- Choosing between copied definitions, symlinks, and host-specific local adapters.

Use the host-specific execution skill for running delegated coding work; use this skill for configuration lifecycle and acceptance.

## Safety Contract

- Inspect the active binary and configuration precedence before writing.
- Inspect every source and destination; never replace an unexpected file, directory, or symlink.
- Preserve source repositories during configuration-only tasks unless source changes were explicitly authorized.
- Do not assume unknown configuration fields cause a hard error; many hosts ignore them.
- Verify effective parsed behavior after installation, not only file existence or agent discovery.
- Keep secrets, provider credentials, and private model tokens out of reusable templates.

## Workflow

### 1. Establish the active host and scope

Record:

- the exact CLI binary selected by the current shell;
- its version;
- global and project configuration roots;
- configuration precedence and runtime overrides;
- whether the request is global, project-local, or both.

When behavior differs between interactive terminals and automation, resolve every candidate binary before editing configuration.

### 2. Inspect source definitions and destinations

For each definition, record:

- role name and filename-derived identifier;
- declared mode, model, prompt, tools, and permissions;
- source ownership and whether it may be edited;
- destination state: absent, regular file, directory, or symlink;
- for symlinks, the exact target and resolved path.

Refuse to overwrite an unexpected destination. A destination created earlier in the same verified operation may be replaced only after rechecking its exact identity.

### 3. Validate against the current host schema

Consult current official host documentation when the CLI evolves rapidly. Check exact field names, value shapes, permission/tool identifiers, and deprecations.

Do not infer compatibility from successful discovery. A host may accept the filename and prompt body while silently ignoring an obsolete permission block. Distinguish:

- **discovered**: the host lists the role;
- **parsed**: intended fields appear in effective configuration;
- **enforced**: a focused probe demonstrates the restriction or route when safe and practical.

Treat configuration shape as a separate decision from schema correctness. Preserve the user's existing JSONC-versus-Markdown structure when the request is only a syntax correction. Do not turn a permission migration into an unsolicited layout migration.

### 4. Choose copy, symlink, or local adapter

Prefer a **symlink** when:

- the source is stable and expected to remain at that path;
- its schema matches the active host;
- automatic propagation of source updates is desired.

Prefer a **copy** when:

- the source must remain immutable;
- global configuration needs local model/provider choices;
- independent local evolution is intentional.

Prefer a **host-specific local adapter** when:

- the source semantics are sound but its schema is obsolete;
- modifying the source repository is outside the request;
- a small translation can preserve the intended role and restrictions.

Never write through a symlink merely to make a local adaptation; that edits the source. Verify and remove only the exact link you created, then write the local adapter.

### 5. Install conservatively

Create only the required configuration directory and explicit files. Set model fields explicitly only when the user requested model routing or the source contract requires it. Otherwise preserve intentional host-default selection and report that choice.

When adapting a definition, change only host syntax, not role semantics. Preserve its prompt, scope, access boundary, and authority contract.

### 6. Verify effective configuration

Use the host's native inspection command and check every installed role individually:

1. Expected role name appears.
2. Role mode/type is correct.
3. Model routing is explicit or intentionally inherited.
4. Intended write restrictions are present.
5. Intended nested-agent restrictions are present.
6. The host reports no parse or provider error.

If the inspection output is verbose, parse it programmatically and assert the expected fields. A green exit code with missing permission rules is a failed acceptance, not success.

Use a focused behavioral smoke test only when it is safe, inexpensive, and materially stronger than configuration inspection. Do not provoke a destructive action merely to prove it is denied.

### 7. Verify source and report

For configuration-only tasks, confirm the source repository still has its prior working-tree state. Report:

- destination paths;
- copy, symlink, or adapter choice and why;
- roles actually discovered;
- effective permissions and model routing;
- any source/schema mismatch found;
- whether the source repository was changed.

## Pitfalls

- Role discovery can succeed while obsolete frontmatter is silently ignored.
- Permission names often describe host tools, not conceptual actions; verify the current identifier instead of translating by intuition.
- Copying definitions improves isolation but stops automatic upstream propagation; state that tradeoff.
- Symlinks propagate both fixes and regressions immediately; use them only after schema validation.
- A reviewer prompt that says “do not edit” is not equivalent to an enforced edit denial.
- An `edit: deny` rule may cover built-in write/edit/patch tools without preventing writes through `bash`; deny or narrowly allowlist Bash when hard read-only behavior is required.
- A worker prompt that says “do not spawn children” is not equivalent to an enforced nested-agent denial.
- Do not turn a configuration request into an unapproved source-repository change merely because the source template is outdated.

## Host References

- `references/opencode-global-agents.md` — OpenCode JSONC/Markdown agent structure, permission migration, Stow installation, and acceptance checks.
