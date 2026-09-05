---
name: coding-agent-cli-inspection
description: "Use when inspecting coding-agent CLI accounts and usage."
version: 1.0.0
license: MIT
metadata:
  hermes:
    category: autonomous-ai-agents
    tags: [cli, coding-agents, account, usage, diagnostics]
---

# Coding-Agent CLI Inspection

Use this skill when the user asks what an installed coding-agent CLI can report about its account, authentication, subscription, models, quota, usage, limits, or supported commands. This is an inspection workflow, not a development-delegation workflow.

## Core Boundary

Honor the requested interface literally. If the user asks to check through the command line, stay within the official CLI surface:

1. Inspect the installed CLI's live top-level help and version.
2. Inspect help for plausible account/status/about/usage commands.
3. Run only read-only commands that the live help confirms.
4. Report exactly what the CLI exposes and what it does not expose in that installed version.
5. If the requested datum is not available through the CLI, stop. Do not silently escalate to a desktop app, browser dashboard, private endpoint, local credential database, reverse-engineered API, or token extraction.

A broader fallback is permitted only when the user explicitly asks for it after hearing the CLI limitation.

## Discovery Procedure

### 1. Identify the executable

Use the product's installed command name and verify it with its version command. Do not assume the desktop app and CLI expose the same features.

### 2. Read live help before probing

Run the equivalent of:

```text
<cli> --version
<cli> --help
```

From the returned command list, identify likely read-only commands such as `status`, `whoami`, `about`, `models`, `account`, `limits`, or `usage`.

### 3. Inspect candidate subcommand help

For every relevant command actually listed, inspect its help before execution:

```text
<cli> <command> --help
```

If a suspected command is absent, one bounded `help <command>` probe may be used to confirm that the installed version does not recognize it. Do not brute-force undocumented command names.

### 4. Run safe read-only commands

Prefer structured output such as `--format json` when advertised. Never print access tokens, refresh tokens, API keys, cookies, or local credential values. Account email, plan tier, model list, and authentication state may be summarized when they are normal output of the official CLI and relevant to the request.

### 5. State the capability boundary precisely

Distinguish among:

- supported and returned by the CLI;
- supported but requiring authentication or configuration;
- not listed in the installed CLI version;
- exposed only by some other interface, which remains out of scope unless the user asks to broaden the method.

Avoid timeless negative claims. Say, for example, "the installed CLI version does not list a usage command" rather than "the product can never show usage."

## User-Specific Workflow Preference

For account or usage checks, when Kenan specifies command-line inspection, treat that as a hard scope boundary. First look for an official CLI command or flag. If none exists, report the limitation briefly and stop; do not open the product UI or web dashboard and do not reverse-engineer private APIs.

## Side-Effect Hygiene

- Do not launch a desktop application merely to inspect CLI capability.
- If the task accidentally launched a process that was not running beforehand, close only that process and verify it stopped.
- Authentication mutations (`login`, `logout`, token refresh scripts, keychain edits) are not inspection and require explicit user intent.
- Do not use local credential databases as an alternate account API during a CLI-only request.

## Verification Checklist

Before reporting completion, verify:

- the installed CLI version was read live;
- the top-level help was inspected;
- relevant listed subcommand help was inspected;
- only read-only official CLI commands were run;
- no secret values were printed;
- the conclusion is scoped to the installed version;
- no GUI, web, or private-API fallback was used without explicit permission.

## Provider References

- Cursor Agent CLI commands and the verified usage-capability probe are summarized in [`references/cursor-agent-cli.md`](references/cursor-agent-cli.md). Re-run live help because commands can change between releases.
