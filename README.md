# Code Modernization Plugin

Point Claude at a legacy codebase — COBOL, legacy Java/C++/.NET, monolith web apps — and get back: an executive assessment, an interactive architecture map, the business rules mined out of the code, a steering-committee-ready modernization brief, and scaffolded or transformed new code with a behavior-equivalence test harness so you can prove nothing drifted.

It works by enforcing a sequence, because modernization usually fails when teams skip steps — transforming code before understanding it, or shipping without a harness to catch behavior drift:

```
preflight → assess → map → extract-rules → brief → (reimagine | transform | uplift) → harden
```

The discovery commands (`assess`, `map`, `extract-rules`) write artifacts to `analysis/<system>/`. `brief` synthesizes them into an approval gate. The three build commands write under `modernized/` (`transform` to `<system>/<module>/`, `reimagine` to `<system>-reimagined/`, `uplift` to `<system>-uplifted/`) and are three different *methods* — the brief recommends which one fits:

- **`transform`** — cross-stack rewrite from extracted intent (e.g. COBOL → Java).
- **`reimagine`** — greenfield rebuild on a new architecture.
- **`uplift`** — same-stack version bump (e.g. .NET Framework → .NET 8) that *preserves* the code and fixes only the version deltas.

![Interactive topology map of AWS CardDemo — domains as containers, modules sized by lines of code, dependency edges colored by kind, entry points ringed](assets/topology-viewer-screenshot.jpg)

## Install

```
/plugin install code-modernization@claude-plugins-official
```

## Quickstart

Each command takes a `<system-dir>` and assumes the code lives at `legacy/<system-dir>/`. Artifacts land in `analysis/<system-dir>/`; new code under `modernized/`. If your code is elsewhere, symlink it: `mkdir -p legacy && ln -s /path/to/code legacy/billing`.

Plugin commands are namespaced, so type the full name — `/code-modernization:modernize-…` (autocomplete finds it from `/modernize`). Flags go after the positional arguments (`/code-modernization:modernize-harden billing --show-secrets`): the first argument is the system directory, except for `assess --portfolio`, whose mode flag comes first.

Try the first three on your own codebase — each produces a standalone artifact, so you can stop and review at any point:

```bash
/code-modernization:modernize-preflight billing   # is my environment ready?
/code-modernization:modernize-assess billing      # what am I dealing with?
/code-modernization:modernize-map billing         # show me the structure (opens an interactive map)
```

Then the full path:

```bash
/code-modernization:modernize-extract-rules billing                         # mine business rules → testable Rule Cards
/code-modernization:modernize-brief billing java-spring                     # the plan a steering committee approves (HITL gate)
/code-modernization:modernize-transform billing interest-calc java-spring   # …or reimagine, or uplift — see Commands
/code-modernization:modernize-harden billing                                # security pass on the still-running legacy system
/code-modernization:modernize-status billing                                # where am I, what's stale, what's next
```

## Commands

Run in order; you can stop and review after any step. Each command stands alone except `brief`, which needs `assess`, `map` and `extract-rules` first. If a command stops or fails, `/code-modernization:modernize-status <system-dir>` names the next step; an interrupted `extract-rules` run [can resume](#dynamic-workflow-orchestration).

- **`/code-modernization:modernize-preflight <system-dir> [target-stack]`** — Environment readiness check. Asks you, in a pop-up, the five questions the source can't answer (scope, whether you can build and test locally, bespoke build infrastructure, prior attempts, what's off limits) and records your answers verbatim. Then it detects the legacy stack, checks analysis tooling, reads the CI/build definition, smoke-tests the toolchain against the real code (and, if you name a target stack, that a throwaway project builds on it here), inventories missing includes / deployment descriptors, and checks the **scope boundary** — whether `<system-dir>` is a slice of a larger repo and what outside it depends on it. Produces `PREFLIGHT.md` with a per-command Ready / Ready-with-gaps / Not-ready verdict.

- **`/code-modernization:modernize-assess <system-dir> [--show-secrets]`** *(or `--portfolio <parent-dir>`)* — Inventory: languages, complexity, tech debt, security posture, and a COCOMO complexity index ([see note](#a-note-on-cocomo)). Produces `ASSESSMENT.md` + `ARCHITECTURE.mmd`. With `--portfolio`, sweeps every subdirectory and writes a sequencing heat-map (`portfolio.html`).

- **`/code-modernization:modernize-map <system-dir> [--no-describe]`** — Dependency and topology map: call graph, data lineage, entry points, and 2–4 business flows each traced for a persona (the claimant, the auditor). Produces `topology.json` and an **interactive zoomable `TOPOLOGY.html`** (circle-pack sized by LOC, edge toggles, search, and a persona-flow walkthrough), plus small `.mmd` diagrams for docs. Each node also gets a short plain-language description in the sidebar, written by one agent per node from just that node's source and links; `--no-describe` skips that step.

- **`/code-modernization:modernize-extract-rules <system-dir> [module-pattern]`** — Mine the business rules — calculations, validations, eligibility, state transitions — into Given/When/Then "Rule Cards" with `file:line` citations and confidence ratings. With the Workflow tool, anything but a tiny system is extracted in per-module shards (from `map`'s `topology.json` if present, else the directory tree), so each extractor reads one focused slice. A large run shows an estimate and asks before it starts. Produces `BUSINESS_RULES.md` + `DATA_OBJECTS.md`.

- **`/code-modernization:modernize-brief <system-dir> [target-stack]`** — Synthesize discovery into a phased **Modernization Brief**: target architecture, phase plan, persona walkthroughs, behavior contract, and an approval block. Reads the discovery artifacts and **stops if any are missing**. Stops for your explicit approval as a human-in-the-loop gate, in plan mode if the session supports it. For a same-stack uplift it also requires the **delta catalog**, since an uplift's phase order is decided by its version deltas. The execution commands read the brief and treat each phase's entry criteria as gates, so editing the brief steers execution.

- **`/code-modernization:modernize-reimagine <system-dir> <target-vision>`** — Greenfield rebuild from extracted intent. Mines a spec, designs and adversarially reviews a target architecture, then scaffolds services with executable acceptance tests under `modernized/<system>-reimagined/`. Two human checkpoints.

- **`/code-modernization:modernize-transform <system-dir> <module> <target-stack>`** — Surgical single-module rewrite (strangler-fig: replace one piece while the legacy system keeps running). Plans first (approval gate), writes characterization tests, then an idiomatic implementation, and proves equivalence by running the tests. Produces `TRANSFORMATION_NOTES.md`.

- **`/code-modernization:modernize-uplift <system-dir> <source-version> <target-version> [project-pattern]`** — Same-stack version bump (e.g. `.NET Framework 4.8` → `.NET 8`, Spring Boot 2 → 3) — the common case `transform` gets wrong by rewriting. Preserves the code and makes the smallest diffs that compile and behave identically, driven by a **delta catalog** (the known breaking changes that *this* code actually hits) and the ecosystem's migration tooling. Equivalence is proven by running the test suite on both the old and new runtime where both can run here (otherwise it falls back to characterization tests, like `transform`). Migration is **pilot-first**: one representative project is migrated end-to-end in-session and its lessons written to a `PLAYBOOK.md` before anything else is touched; the rest then fan out, one agent per project, in **dependency-aware escalating batches behind a circuit breaker**. Produces `DELTA_CATALOG.md`, `BASELINE.md`, `PLAYBOOK.md` + `UPLIFT_NOTES.md`. If the catalog shows most of the code is forced to change, it tells you to use `transform` instead.

- **`/code-modernization:modernize-harden <system-dir> [--show-secrets]`** — Security pass on the **legacy** system: OWASP/CWE, dependency CVEs, secrets, injection. Produces `SECURITY_FINDINGS.md` (ranked) and a reviewed `security_remediation.patch`. **Never edits `legacy/`** — you review and apply the patch yourself. Useful while the legacy system keeps running in production during migration.

- **`/code-modernization:modernize-status <system-dir>`** — Read-only progress report: artifact inventory, staleness flags, secrets-hygiene checks, and the single most useful next command.

## Agents

Specialist subagents invoked by the commands (or directly):

- **`legacy-analyst`** — Reads legacy code (COBOL, EJB, classic ASP, …) and produces structural summaries; spots implicit dependencies and "JOBOL" (procedural code in modern syntax). *(assess, map, extract-rules, reimagine)*
- **`business-rules-extractor`** — Mines domain rules from procedural code with source citations. *(extract-rules, reimagine)*
- **`architecture-critic`** — Skeptical reviewer of target designs and transformed code; flags over-engineering. *(reimagine, transform, uplift)*
- **`security-auditor`** — Auth, input validation, secrets, dependency CVEs. *(assess, harden)*
- **`test-engineer`** — Characterization and equivalence tests that pin legacy behavior. *(transform, uplift)*
- **`version-delta-analyst`** — Finds the breaking changes between two versions of one stack that bite *this* codebase, and drives the ecosystem migration tool. *(uplift)*
- **`uplift-migrator`** — Migrates one project/module of an in-flight uplift by following the pilot's playbook, then runs that unit's real build to prove it; refuses to migrate anything if no playbook exists yet. Writes only inside its own unit's directory. *(uplift)*
- **`scaffolder`** — Builds one service of a reimagined system; writes only within its own `modernized/.../<service>/` directory. *(reimagine)*

## Live progress pane (early access)

While the commands run, the plugin can draw a live pane beside the transcript: for a system in any language, what the
commands are doing to it, how far along each part is, and what to run next. It is built on Claude Code's function hooks,
which are early access and off by default. Start with the flag to turn them on:

```sh
CLAUDE_CODE_ENABLE_FUNCTION_HOOKS=1 claude
```

Without the flag nothing changes: the commands, agents and workflows behave the same and the pane never loads. Everything
it shows is read from the artifacts the commands write under `analysis/<system>/` and `modernized/<system>/`, and from the
legacy tree itself. Nothing is inferred by a model, and a fact that is not on disk is shown as absent. The hooks are written
against a feature that may change between releases; they were run on 2.1.280 and 2.1.283.

### What it adds

**A progress pane with an estate map.** Docked beside the transcript, for whatever system is under `legacy/` and in
whatever language: the system and what the plugin's commands are doing to it, which steps are done, a treemap of its
code, each unit of work and where it stands, what needs attention, and the next command to run.

- **Any language.** The pane reads no language of its own. The map comes from `topology.json` when `/modernize-map` has run.
  Until then it is read off the legacy tree: one tile per build module where the tree has build files (Maven, Gradle, npm,
  .NET projects, Go, Cargo, Python packages, Composer, and more), one per source file for a tree without them, one per
  directory for a tree too big for that. Its header names the languages by the share of the code (COBOL, Java, C#, PHP,
  Perl, RPG, and any other by file type) and how many units it found.
- **Any way of working.** It follows the track whose artifacts are newest: a **rewrite** (map, rules, brief, transform), a
  same-stack **uplift** (delta catalog, baseline, playbook, working copy), or a **reimagine** (spec, architecture, services).
  Each has its own steps, its own next command, and tiles coloured by its own progress. An uplift's modules are set against
  the baseline: *matches baseline* means every test that passed on the source runtime still passes and none is missing;
  *worse than baseline* means more failures than it had (failures the baseline already had are not called worse). Set
  `track` to pin one.
- **Any test runner.** A module's tests come from the reports it left (JUnit XML in the usual places, Visual Studio `.trx`,
  or `.modernize/test-report.json`), and, where a runner leaves none, from a test command run in the module's directory during
  the session (Maven, Gradle, pytest, Jest, dotnet, go, cargo, rspec, phpunit and more).
- **A tile lights up** for a few seconds when Claude or one of its agents reads (blue) or writes (yellow) a file under it,
  in the legacy tree or in an uplift's working copy, so a fan-out is something you watch move across the system.
- **Show it and hide it.** It opens by itself under the fullscreen layout once the workspace has an `analysis/` directory.
  A **hide** button at the top of the pane closes it. While it is hidden, one row above the prompt says where the
  workspace stands and holds a **show pane** button that brings it back, on a terminal too narrow to dock it as well as a wide
  one. `/modernize-panel` does the same from the keyboard, and shows the pane for a legacy tree nothing has analysed yet.
  Set `panel` to `command` to have it open only on request, or `off` to have no pane and no button.

**X-ray reads.** When Claude reads a file under `legacy/<system>/`, what the analysis already
established about that file rides along as context only the model sees: the map's callers,
callees and data stores, the business flows through it, the rules in `BUSINESS_RULES.md` that
cite it (narrowed to the lines just read when the read was a window), any rule a reviewer
disputed, and whether it has already been transformed. In an uplift it carries the module's
baseline (what fails on the source runtime is part of the oracle, so it is reproduced, not fixed),
where the module stands in the working copy, and the deltas the catalog cites the file under. The model stops re-deriving what three
stages already worked out, and stops calling code dead that the map knows is reached. A read
that misses because a cited path was taken from the workspace root is told where the file is
under the legacy root.

**A review deck for business rules.** `/modernize-review [flagged|p0|all] [filter]` pages through
rule cards in the band above the prompt: the rule, its citation, Given / When / Then, the
suspected defect, the question for an SME. From an empty prompt, `1` confirms, `2` marks it wrong,
`3` sends it to discussion, `6` shows the cited legacy lines. Verdicts go to
`analysis/<system>/RULE_REVIEWS.json` and a readable `RULE_REVIEWS.md`; the agent-written rules
file is never edited. Disputed rules show up in the pane and in later x-ray notes.

**A sign-off dialog.** `/modernize-sign [name, role]` fills in the brief's approval block: who,
when, and whether it covers Phase 1 or the full plan.

**A fleet view.** Every agent loop that makes a tool call is counted, including a workflow's
agents, which `$.agent.list()` does not name. The pane shows how many are active and done, and
what the most recent are doing. When agents fail the same way (paths, numbers and quoted values
folded out, and one cause that words itself differently per command folded together), the pane
lists it with an example of what the failing calls were aimed at. The transcript says so once it
is a pattern for a fleet that size (three agents, or one in twenty), and once more if it spreads
fivefold: one cause across agents belongs in the playbook, not in each agent. A bare exit code
or a malformed call is not a cause and is not counted as one.

### Pane commands

| | |
|---|---|
| `/modernize-panel [open\|close\|json]` | Show or hide the pane (the same switch as its **hide** and **show pane** buttons); `json` prints the reading it draws from. |
| `/modernize-review [flagged\|p0\|all] [filter]` | Review rules. `flagged` (default) is the P0 rules with a defect, an SME note or less than High confidence. The filter matches an id, a domain, a title or a cited file. |
| `/modernize-sign [name, role]` | Sign the brief's approval block. |

### Pane options

Set in `/config`, or under `pluginConfigs` in settings.

| Option | Default | |
|---|---|---|
| `system` | first under `analysis/`, else under `legacy/` | The system to follow. |
| `track` | `auto` | `auto` follows whichever way the commands are working on the system; `transform`, `uplift` or `reimagine` pins one. |
| `panel` | `auto` | `auto` opens the pane by itself and draws the show button while it is hidden; `command` opens it only when the button or `/modernize-panel` asks; `off` neither opens it nor draws the button. |
| `xray` | on | Attach analysis context to legacy reads. |
| `commandPrefix` | `/code-modernization:modernize-` | How the pane writes the plugin's commands. |
| `legacyDir` | `legacy` | The read-only tree. |

### Pane keys

Hotkeys work in the band above the prompt (the review deck's digits, from an empty prompt). A
pane's buttons are pressed by clicking, or `ctrl+x tab` to give the pane the keyboard, then Tab
and Enter.

### What the pane does not do

- An uplift's changed modules are found by comparing the working copy with the legacy tree by file name and size, with the
  file API alone: the pane runs no program inside either tree. An edit that keeps a file exactly the same size is not seen by
  that comparison, but a test run in the module, or a write during the session, shows it.
- Sizes are lines where the map gave them and bytes of source where the estate was read off the tree; a single file counts for
  at most 400 KB, so a binary in a test folder is not a system's bulk.
- It never runs a command by itself. The pane's **next** button puts the command in the prompt
  box; a person presses Enter.
- It does not call a model. The brief's phases and approval are read by pattern from the file;
  what cannot be read that way is shown as unknown, not guessed.
- It only watches. It does not block or rewrite any edit or command; the workspace's own permission rules
  (`Edit(/legacy/**)` denied, see Recommended workspace setup) are what keep `legacy/` read-only.
- The cut-over console (live legacy-versus-modern traffic diff with automatic fallback) and
  approvals from a phone are not built: both need an environment this repository cannot test.

To work on the pane, `hooks/register.ts` is the module: it binds the engine at `session.start` and wires the hooks, and
everything it calls is a plain function under `hooks/`. `claude plugin test .` runs the tests in `tests/` (parsers, layout,
estates in eight stacks, and the hooks through the engine's own `$`); `tsc -p .` typechecks them against the
declaration file `/plugin-types` writes into `.claude/types/`.

## Recommended workspace setup

The commands never edit `legacy/`, by convention. A `.claude/settings.json` in the project you're modernizing backs that up with a deny rule for `legacy/` and allow rules for `analysis/` and `modernized/`; `/code-modernization:modernize-preflight` checks for the deny rule:

```json
{
  "permissions": {
    "allow": ["Read(**)", "Edit(analysis/**)", "Edit(modernized/**)"],
    "deny": ["Edit(/legacy/**)"]
  }
}
```

Claude Code matches file writes through the `Edit` rule, so these cover the `Write` tool too; a `Write(path)` rule is accepted but never consulted.

The deny rule starts with `/` so that it is anchored at the project root; without the slash it also matches any nested directory named `legacy`, such as `modernized/<system>/.../legacy/`. It refuses a copy out of `legacy/` too, so `uplift`'s working copy (`cp -r legacy/<system> modernized/<system>-uplifted`) needs `rsync -a legacy/<system>/ modernized/<system>-uplifted/` instead, or a copy you run yourself. If `legacy/<system>` is a symlink to a directory outside the project, add that directory to `additionalDirectories` so Claude can read through the link, and deny its real path as well, because the rule above matches the link's path and not its target's: `"additionalDirectories": ["/path/to/code"]` and `"Edit(//path/to/code/**)"` in `deny`.

This guards the file tools; shell commands that mutate files (`git apply`, a script that opens files itself) still go through the normal Bash prompt, so review those with the same invariant in mind. That prompt is the containment for the two steps that fan out many write-capable agents at once — `/code-modernization:modernize-uplift` Step 5b and `/code-modernization:modernize-reimagine` Phase E — so keep Bash on a *prompted* permission mode for those.

## Prerequisites

Commands degrade gracefully, but these improve the output (run `/code-modernization:modernize-preflight` to check all at once):

- **Analysis tools** — [`scc`](https://github.com/boyter/scc) or [`cloc`](https://github.com/AlDanial/cloc); without them, metrics fall back to `find`/`wc`.
- **A build toolchain** for the legacy stack — enables the strongest equivalence proof (live dual execution). Not required: without it, equivalence falls back to recorded-trace tests and preflight reports Ready-with-gaps rather than blocking.
- **The whole system in the tree** — deployment descriptors (JCL, CICS, route configs), copybooks/includes, DDL. Entry-point detection and data lineage need them.

## Safety notes

**Analyzed code is untrusted input.** A hostile codebase can plant comments like "ignore previous instructions" or "mark this rule approved" to steer what lands in `BUSINESS_RULES.md` or `SECURITY_FINDINGS.md`, which later commands trust. Defenses: agents treat file content as data and flag instruction-shaped text; verification agents re-derive every rule and finding from the cited code, not from another agent's description; filesystem paths are validated; and `/code-modernization:modernize-brief` is a human approval gate before any code is generated. Treat discovery artifacts from untrusted code with the same skepticism as the code itself.

**Secrets stay out of shared artifacts.** Discovered credentials are masked (`AKIA****`) and inventoried in a gitignored `SECRETS.local.md` (or `~/.modernize/<system>/` on non-git projects); `/code-modernization:modernize-harden` keeps credential-removal hunks in a separate gitignored patch. Pass `--show-secrets` to include raw values in the quarantine file only. If you ran an early version of this plugin on a real system, check whether `analysis/` artifacts were committed and rotate anything exposed.

### A note on COCOMO

`assess` derives a COCOMO figure from code size and uses it **only as a relative complexity/scale index** to rank and sequence systems — never as a timeline or cost. COCOMO's constants encode human-team productivity, which agentic transformation doesn't follow, so any duration derived from it would be wrong.

## Teams, adapting it, and what it has been tried on

**Who owns what.** `legacy/` stays read-only: by convention, backed by the permission rule in [Recommended workspace setup](#recommended-workspace-setup). `analysis/<system>/` holds outputs a named person should review, not facts; `modernized/` is code and gets ordinary code review. The commands never commit, so commit both yourself; `assess` and `harden` keep the credential inventory and the credential patch out of git through `analysis/.gitignore`. Suggested reviewers, from what each artifact contains (the commands stop for a human at several gates but never check who that is):

| Artifact | Contains | Suggested reviewer |
| --- | --- | --- |
| `PREFLIGHT.md` | the five answers only a person can give, the scope-boundary finding, tool and build checks | whoever owns the build |
| `ASSESSMENT.md` | inventory, technical debt, security posture, relative scale, recommended pattern | the engineering lead or sponsor |
| `topology.json`, `TOPOLOGY.html` | call graph, data lineage, persona flows | engineers who know the system |
| `BUSINESS_RULES.md` | Rule Cards with citations, priority and confidence, and a closing list of questions for experts | a business expert per domain; start with the P0 rules and that list |
| `MODERNIZATION_BRIEF.md` | phases, entry and exit criteria, behavior contract, approval block | the approver, who steers execution by editing it |
| `SECURITY_FINDINGS.md`, the patch | ranked findings, a reviewed remediation patch | a security engineer, who applies the patch |

State lives in files, not in chat: later commands read the brief's criteria and the answers in `PREFLIGHT.md`, not your conversation, so a second person or a fresh session can run `/code-modernization:modernize-status <system-dir>` and continue from the next command it names.

**Trying it on a live repository.** `preflight` and `assess` write their reports under `analysis/` and change no source file. Two side effects: preflight's smoke test compiles one file and, where the system has a build system, restores and builds one small project or module with it; that writes build output (and, for some tools, updates lockfiles) wherever the build normally does, possibly inside `legacy/`, and outside a git repository `assess` writes any credential inventory to `~/.modernize/<system>/`.

**Adapting it.** Commands, agents and workflows are plain markdown and JavaScript under Apache 2.0. Fork it to change the prompts, the gates or the steps for your stack.

**Repeatability.** A model does the extraction, so two runs of `extract-rules` on the same estate, or on different models, can find different rules and number them differently. Treat `BUSINESS_RULES.md` as reviewed output, not a deterministic build artifact. Headings are always `### RULE-NNN: <name>`, so later steps can find rules whichever run wrote them. The verification steps and the closing question list help a person review what was found; they do not make two runs identical.

**Permissions and toolchain.** The commands write files, so a session that asks before every edit keeps stopping: use accept-edits mode or the allow rules in Recommended workspace setup. Shell commands still ask, even in accept-edits mode: `git check-ignore`, `python3` scripts, analysis tools such as `scc`, `cp -r`, and the build and test commands of your stacks, and so does anything outside the project, such as `~/.modernize/`. Writes to sensitive paths such as `.git/`, `.mvn/` and `.npmrc` ask even with an allow rule. `transform`, `reimagine` and `uplift` also need a toolchain that builds and tests the target stack; `preflight` checks it when you name one.

**What it has been tried on.** The one example in this README, the map at the top, is AWS CardDemo, a public COBOL, CICS and JCL sample. Any other stack goes through the same generic path (`preflight` detects it from file extensions and manifests), but nothing in this plugin shows one being run, so expect to adapt.

## Dynamic workflow orchestration

On Claude Code builds with the Workflow tool, five commands (`extract-rules`, `harden`, `assess --portfolio`, `reimagine`, `uplift`) run as scripted multi-agent orchestrations that fan out more agents for deeper coverage — looping until findings stabilize, and adversarially verifying each finding before it's written. `uplift`'s migration fan-out runs in dependency-aware escalating batches behind a per-batch **circuit breaker**, so a playbook that stops working is caught within a handful of agents and the spend stops until it is revised. A stopped or failed `extract-rules` (or `assess --portfolio`) run is **resumable** in the same session: the command re-runs the workflow with the run's ID, and every agent that finished before the stop replays from the run's journal instead of running again. Shards whose agents failed outright are reported and re-run on their own in a follow-up run. They fall back to direct subagent fan-out on older builds automatically; no configuration needed. Invoking the slash command is the opt-in.

## License

Apache 2.0. See `LICENSE`.
