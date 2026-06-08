---
description: Security vulnerability scan with a reviewable remediation patch — OWASP, CWE, CVE, secrets, injection
argument-hint: <system-dir> [--show-secrets]
---

Run a **security hardening pass** on `legacy/$1`: find vulnerabilities, rank
them, and produce a reviewable patch for the critical ones.

This command never edits `legacy/` — it writes findings and a proposed patch
to `analysis/$1/`. The user reviews and applies (or not).

## Step 0 — Secrets quarantine setup

Findings files get shared, committed, and pasted into decks — discovered
credential values must never land in them. Before any scanning:

1. Ensure `analysis/.gitignore` exists and contains the line
   `SECRETS.local.md`. Create the file or append the line if missing.
2. If the project is a git repo, verify with
   `git check-ignore -q analysis/$1/SECRETS.local.md` — if that exits
   non-zero, fix the ignore rule before proceeding. Do not write any
   findings until this check passes (skip the check only if there is no
   git repo).

All secret values in every artifact this command produces are **masked**
(`AKIA****`, `password=****`) and cited by `file:line`. The one exception:
if the user passed `--show-secrets`, raw values may appear in
`analysis/$1/SECRETS.local.md` (gitignored above) and nowhere else —
never in SECURITY_FINDINGS.md or the patch commentary.

## Scan

Spawn the **security-auditor** subagent:

"Adversarially audit legacy/$1 for security vulnerabilities. Cover what's
relevant to the stack: injection (SQL/NoSQL/OS command/template), broken
auth, sensitive data exposure, access control gaps, insecure deserialization,
hardcoded secrets, vulnerable dependency versions, missing input validation,
path traversal. For each finding return: CWE ID, severity
(Critical/High/Med/Low), file:line, one-sentence exploit scenario, and
recommended fix. Run any available SAST tooling (npm audit, pip-audit,
OWASP dependency-check) and include its raw output. Mask every discovered
credential value per your secret-handling rules — file:line plus a 2–4
character masked preview, never the value itself."

## Triage

Write `analysis/$1/SECURITY_FINDINGS.md`:
- Summary scorecard (count by severity, top CWE categories)
- Findings table sorted by severity
- Dependency CVE table (package, installed version, CVE, fixed version)

If any hardcoded credentials were found, also write
`analysis/$1/SECRETS.local.md` (the gitignored quarantine file from Step 0):
one row per credential — masked preview, `file:line`, credential type, what
it appears to grant access to, production/test guess, and a rotation
recommendation. With `--show-secrets`, append the raw value column here —
this file only. SECURITY_FINDINGS.md gets a one-line pointer:
"N hardcoded credentials found — inventory in SECRETS.local.md (gitignored;
not for sharing)."

## Remediate

For each **Critical** and **High** finding, draft a minimal, targeted fix.
Do **not** edit `legacy/` — write all fixes as a single unified diff to
`analysis/$1/security_remediation.patch`, with a comment line above each
hunk citing the finding ID it addresses (`# SEC-001: parameterize the query`).

Add a **Remediation Log** section to SECURITY_FINDINGS.md mapping each
finding ID → one-line summary of the proposed fix and the patch hunk that
implements it.

## Verify

Spawn the **security-auditor** again to **review the patch** against the
original code:

"Review analysis/$1/security_remediation.patch against legacy/$1. For each
hunk: does it fully remediate the cited finding? Does it introduce new
vulnerabilities or change behavior beyond the fix? Return one verdict per
hunk: RESOLVES / PARTIAL / INTRODUCES-RISK, with a one-line reason."

Add a **Patch Review** section to SECURITY_FINDINGS.md with the verdicts.
If any hunk is PARTIAL or INTRODUCES-RISK, revise the patch and re-review.

## Present

Tell the user the artifacts are ready:
- `analysis/$1/SECURITY_FINDINGS.md` — findings, remediation log, patch review
- `analysis/$1/security_remediation.patch` — review, then apply if appropriate
  with `git -C legacy/$1 apply ../../analysis/$1/security_remediation.patch`
- Re-run `/modernize-harden $1` after applying to confirm resolution

Suggest: `glow -p analysis/$1/SECURITY_FINDINGS.md`
