# Cursor Agent CLI Account Inspection

This reference records the verified command surface from Cursor Agent CLI version `2026.08.25-3e8eec8`. Treat it as a snapshot, not a permanent product guarantee; always re-run live help first.

## Safe probe sequence

```text
agent --version
agent --help
agent status --help
agent status --format json
agent about --help
agent about
```

If `usage` is absent from the live top-level command list, one bounded confirmation is sufficient:

```text
agent help usage
```

A non-zero result that prints only the top-level help confirms that this installed version does not recognize `usage` as a command. Stop there during a CLI-only request.

## Fields exposed in this version

`agent status --format json` can expose:

- authentication state;
- whether access and refresh tokens exist, without revealing their values;
- account identity fields;
- team identifier.

`agent about` can expose:

- CLI version and update state;
- configured model;
- subscription tier;
- OS, shell, and account email.

## Usage limitation observed

For the verified version above, neither the top-level options nor commands included a usage, quota, spend, remaining-credit, or billing-cycle report. `status` and `about` provided account and plan metadata only.

Phrase this as a version-scoped finding: "The installed Cursor Agent CLI does not list a usage command or flag." Do not turn it into a permanent claim about Cursor.

## Scope boundary

When the user requested command-line inspection, the correct completion was to report the missing CLI capability and stop. Do not substitute:

- Cursor desktop settings;
- the Cursor web dashboard;
- browser automation;
- SQLite credential extraction;
- access-token or refresh-token use;
- private or reverse-engineered dashboard endpoints.

Those are separate methods and require the user to broaden the requested scope explicitly.
