# Delegated writes through sibling artifact symlinks

Use this when a project exposes an agent-owned artifact directory through a relative symlink, for example:

```text
<project>/.dev -> ../development-artifacts/<project>/.dev
```

## Preflight

Before delegating a phase that must write plans, QA records, or architecture docs:

1. Resolve every authorized output path.
2. Compare the resolved path with the delegated agent's writable sandbox root.
3. Distinguish read access from write access: a sandbox may read the symlink target but refuse writes outside the project repository.
4. Preserve separate Git ownership: product changes remain in the product repository; plans and internal records remain in the companion repository.

## Safe recovery after a sandbox refusal

If the delegated run prepared an artifact but could not write through the symlink:

1. Verify the product worktree is clean and the target file is absent or unchanged.
2. Resume the same agent thread so its prepared work and critique state are preserved.
3. Expand filesystem authority only when the sibling artifact write was already authorized.
4. Constrain the retry prompt to the exact output path; prohibit source changes, unrelated repositories, Initiative control files, commits, pushes, releases, and publication.
5. Verify the exact target exists and the product repository stayed untouched.

When an accepted execution plan explicitly includes writes in both the product repository and the sibling artifact target, a project-root-only write sandbox cannot complete it. Use the transport's broader filesystem mode from the start only with an explicit workdir, accepted plan path, exact allowed artifact boundary, and strong external-side-effect prohibitions.

This is a scoped multi-repository transport pattern, not blanket permission to bypass sandboxing. Stop if any newly required write falls outside the accepted repositories or paths.
