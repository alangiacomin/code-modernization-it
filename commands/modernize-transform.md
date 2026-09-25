---
description: Rewrite one legacy module in the target stack, with tests that prove it behaves the same
argument-hint: <system> [module] [target-stack]
arguments: system module target_stack
---

Transform module **`$module`** of `$system` into **$target_stack**, with proof of behavioral
equivalence. This is one vertical slice of the strangler fig; output goes to
`modernized/$system/$module/`.

The code is `legacy/$system`, often a symlink to where it really lives: say where it points (`readlink legacy/$system`) in one line before you start. Run every subagent in the foreground and wait for its result: never end your turn while one is still running. **If `$module` or `$target_stack` is empty**, read
`analysis/$system/MODERNIZATION_BRIEF.md`: take the target stack it names, and the first module of
the earliest phase whose `Command:` is `transform` that has no
`modernized/$system/<module>/TRANSFORMATION_NOTES.md` yet. Say which you picked.

## Step 0 — Toolchain, then the plan (human gate)

**Target stack (required).** The runtime, package manager and test framework must respond
(`java -version` and `mvn -v`, `node -v` and `npm -v`, `python3 -V` and `pytest --version`). If not,
stop and say what to install: a plan gate now would only defer the failure an hour. Point to
`/code-modernization:modernize-preflight $system $target_stack`.

**Legacy stack (advisory, never a blocker).** Try a syntax-only compile of the module. Legacy code
often cannot build locally by nature (CICS and IMS programs have no local translator; the real runtime
is a mainframe you do not have). If it cannot, dual execution is off the table: the tests assert
against **recorded traces and golden-master fixtures** (real production outputs, captured reports,
SME-confirmed examples). Say so in the plan and in `TRANSFORMATION_NOTES.md` ("equivalence is
trace-based; legacy was not executable here"), so reviewers know how strong the proof is.

**The brief is binding.** If `MODERNIZATION_BRIEF.md` exists, find the phase whose `Command:` is this
one and whose `Modules:` include `$module`, and treat its scope, entry criteria, exit criteria and any
edits the user made as binding. An unmet entry criterion is the next step: meet it, never re-plan
around it. If no phase covers `$module`, stop and ask which phase this is.

Read the module's source and the rules in `BUSINESS_RULES.md` that reference it. Then present the
plan and **stop: write no code until the user explicitly approves** (plan mode if available): which
source files are in scope, the target structure, which rules and behaviors it implements, how you will
prove equivalence, and anything ambiguous that needs a human decision now.

## Step 1 — Characterization tests first

Spawn the **test-engineer** subagent: "Write characterization tests for module $module of legacy/$system.
Read the source, identify every observable behavior and encode each as a test with concrete input and
expected output derived from the legacy logic. Target framework: <right for $target_stack>. Write to
`modernized/$system/$module/src/test/`. These tests define 'done'. Follow your secret-handling rules:
no credential from legacy code becomes a fixture; use fake same-shape values and read anything live
from environment variables." Show the user the test file and get a yes before going on.

## Step 2 — Idiomatic transformation

Write the implementation in `modernized/$system/$module/src/main/`. **Write what a senior
$target_stack engineer would write from the *specification*, not from the legacy structure:** do not
mirror COBOL paragraphs as methods or keep names like `WS-TEMP-AMT-X`; use the target's idioms
(records, streams, injection, proper error types). Include the domain model, service logic, API
surface and configuration, and link each class to the rule IDs it implements in a short comment.

## Step 3 — Prove it, and prove the proof can fail

While iterating, run only this module's tests; run the whole suite once before Step 4.

1. **Run the tests** (`cd modernized/$system/$module` and the stack's test command) and show the
   output. Fix and rerun until green.
2. **Count what ran.** Report `equivalence cases executed: N`. A run that executed **zero** cases proved
   nothing, and a comparison test must **fail, never skip,** when its legacy oracle or fixture is
   missing: a suite that is green because everything skipped is not green. If the oracle was
   unreachable, fix that; do not report the suite as passing.
3. **Show the tests can fail.** Temporarily break the new code in one small way that matters (change a
   rounding mode, shift a threshold by one, flip a comparison), confirm at least one test goes red,
   restore it, and record `Canary: <the change> → <N> tests failed` in the notes. If nothing failed,
   the tests do not pin the behavior: strengthen them before going on.
4. **When the legacy code can run here**, also run both systems on the same inputs, save each output
   under `analysis/$system/equivalence/legacy/` and `.../new/`, list the pairs in
   `analysis/$system/equivalence/cases.json` (paths relative to that folder; the schema is at the top of
   `scripts/compare.py`), and run
   `python3 "${CLAUDE_PLUGIN_ROOT}/scripts/compare.py" analysis/$system/equivalence/cases.json --out analysis/$system/EQUIVALENCE.json`.
   That script, not your judgment, decides same or different. Mask only fields that legitimately vary
   (timestamps, generated ids) and say what each mask hides. A difference you accept is recorded with a
   reason in the case's `approvedDifference`, and only a person accepts it.

## Step 4 — Notes and a side-by-side

Write `modernized/$system/$module/TRANSFORMATION_NOTES.md`: a mapping table (legacy file:lines to target
file:lines, per behavior); deliberate deviations with rationale; what was NOT migrated (dead code,
unreachable branches) and why; the canary result and the executed-case count; follow-ups for the next
dependent module. Show one representative behavior side by side
(`diff -y --width=160 <(sed -n '<lines>p' <legacy file>) <target file>`). Never pick a credential-bearing
range, and mask any credential-like literal in the notes: they live in `modernized/` and get committed.

## Step 5 — Architecture review

Spawn the **architecture-critic** subagent to review the code against $target_stack best practice.
Apply HIGH-severity feedback and list the rest in the notes.

Report: tests passing, cases executed, lines of legacy retired, where the artifacts are. Refresh the
report (`python3 "${CLAUDE_PLUGIN_ROOT}/scripts/build_report.py" $system`, a convenience: if it fails or `python3` is missing, say so in one line and carry on). The next step is the brief's next module, or `/code-modernization:modernize-harden $system`
when the phase is done.
