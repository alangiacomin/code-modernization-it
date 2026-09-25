# Live progress pane (early access)

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

## What it adds

**A progress pane with an estate map.** Docked beside the transcript, for whatever system is under `legacy/` (a copy, or a symlink to where the
code lives) and in
whatever language: the system and what the plugin's commands are doing to it, which steps are done, a treemap of its
code, each unit of work and where it stands, what needs attention, and the next command to run.

- **Any language.** The pane reads no language of its own. The map comes from `topology.json` when `/code-modernization:modernize-map` has run.
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

**X-ray reads.** When Claude reads a file in the system's code (`legacy/<system>/`, followed through a symlink), what the analysis already
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

## Pane commands

| | |
|---|---|
| `/modernize-panel [open\|close\|json]` | Show or hide the pane (the same switch as its **hide** and **show pane** buttons); `json` prints the reading it draws from. |
| `/modernize-review [flagged\|p0\|all] [filter]` | Review rules. `flagged` (default) is the P0 rules with a defect, an SME note or less than High confidence. The filter matches an id, a domain, a title or a cited file. |
| `/modernize-sign [name, role]` | Sign the brief's approval block. |

## Pane options

Set in `/config`, or under `pluginConfigs` in settings.

| Option | Default | |
|---|---|---|
| `system` | first under `analysis/`, else under `legacy/` | The system to follow (a name of letters, digits, `-` and `_`). |
| `track` | `auto` | `auto` follows whichever way the commands are working on the system; `transform`, `uplift` or `reimagine` pins one. |
| `panel` | `auto` | `auto` opens the pane by itself and draws the show button while it is hidden; `command` opens it only when the button or `/modernize-panel` asks; `off` neither opens it nor draws the button. |
| `xray` | on | Attach analysis context to legacy reads. |
| `commandPrefix` | `/code-modernization:modernize-` | How the pane writes the plugin's commands. |
| `legacyDir` | `legacy` | The read-only tree. |

## Pane keys

Hotkeys work in the band above the prompt (the review deck's digits, from an empty prompt). A
pane's buttons are pressed by clicking, or `ctrl+x tab` to give the pane the keyboard, then Tab
and Enter.

## What the pane does not do

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
  (`Edit(/legacy/**)` denied, see "Set it up so it runs smoothly" in the plugin README) are what keep the source read-only.
- The cut-over console (live legacy-versus-modern traffic diff with automatic fallback) and
  approvals from a phone are not built: both need an environment this repository cannot test.

To work on the pane, `hooks/register.ts` is the module: it binds the engine at `session.start` and wires the hooks, and
everything it calls is a plain function under `hooks/`. `claude plugin test .` runs the tests in `tests/` (parsers, layout,
estates in eight stacks, and the hooks through the engine's own `$`); `tsc -p .` typechecks them against the
declaration file `/plugin-types` writes into `.claude/types/`.
