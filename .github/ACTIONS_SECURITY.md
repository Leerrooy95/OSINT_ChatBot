# GitHub Actions Security Hardening

This document tracks the required security changes to `.github/workflows/sync_live_data.yml`.

## Required Changes (apply to `sync_live_data.yml`)

### 1. Pin actions to immutable commit SHAs

Replace the floating tag references with full commit SHAs so tags can never be
silently repointed to malicious code (as happened in the March 2026 trivy-action
supply-chain compromise):

```diff
-        uses: actions/checkout@v6
+        uses: actions/checkout@df4cb1c069e1874edd31b4311f1884172cec0e10 # v6
```

```diff
-        uses: actions/setup-python@v6
+        uses: actions/setup-python@a309ff8b426b58ec0e2a45f0f869d46889d02405 # v6
```

### 2. Scope permissions to job level (least privilege)

```diff
-permissions:
-  contents: write
+permissions: {}   # deny all at workflow level
 
 jobs:
   sync-and-verify:
+    permissions:
+      contents: write   # only this job needs write access
```

### 3. Add job timeout

```diff
   sync-and-verify:
     runs-on: ubuntu-latest
+    timeout-minutes: 20
```

## Why This Matters

- **SHA pinning** — A commit SHA is immutable; a tag is not. Anyone with push access
  to the upstream action repo can repoint the tag to malicious code.
- **Least-privilege permissions** — The workflow-level `contents: write` grants write
  access to every job. Jobs that only read data should not have write permissions.
- **Timeout** — Without a timeout, a hung job runs for 360 minutes (GitHub default),
  burning your monthly free-tier quota.

## References

- [GitHub Well-Architected: Securing GitHub Actions Workflows](https://wellarchitected.github.com/library/application-security/recommendations/actions-security/)
- [Wiz: Hardening GitHub Actions — Lessons from Recent Attacks](https://www.wiz.io/blog/github-actions-security-guide)
