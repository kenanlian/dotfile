# Output recovery

This is an output-only recovery turn for a coding-agent Job. Output-only submission: no further analysis, implementation, or workspace modification.

- Job: {{jobId}} / {{idempotencyKey}} / task {{taskId}} / stage {{stage}} / attempt {{attempt}}
- Repository: {{repoRoot}}
- Permission: read-only. Do not write, edit, commit, push, tag, release, deploy, or otherwise modify the workspace. Cursor-native Subagents, if used at all, must also remain read-only.

Cursor uses native global/project Skill discovery (no explicit Skill list is mounted). Internal delegation uses Cursor-native Subagents. `{{submitTool}}` is the only report channel; call it exactly once with the typed payload as the final action (no terminate semantics; the process ends after submit).

- Submit binding for THIS recovery phase ({{phase}}): jobId `{{jobId}}`, jobSha256 `{{jobSha256}}`, stage `{{stage}}`, expectedTool `{{submitTool}}`, runNonce `{{runNonce}}`. The same values are in `{{submitConfigPath}}`. Do not reuse any primary-phase runNonce or submit-bridge config.

Submit the already-prepared Stage output through `{{submitTool}}` (schema {{outputSchema}}). Do not continue analyzing, implementing, or modifying the workspace.
Do not put the payload in the final message. Do not serialize YAML. Do not wrap JSON in Markdown fences as the report.
Call `{{submitTool}}` exactly once with a complete, schema-valid typed payload as the final action. An error result from the submit tool fails the run; a later corrected call is not accepted.
