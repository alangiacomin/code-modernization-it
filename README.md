# Code Modernization

Point Claude at a legacy codebase (COBOL, Java, .NET, PHP, Perl, Python 2, C and more) and get an assessment, an interactive map, the business rules mined out of the code with citations, a plan you approve, and rewritten or upgraded code with tests that prove it still behaves the same.

![Interactive topology map of AWS CardDemo — domains as containers, modules sized by lines of code, dependency edges colored by kind, entry points ringed](assets/topology-viewer-screenshot.jpg)

## Install

```
/plugin install code-modernization@claude-plugins-official
```

## Start here

1. **Point it at your code.** In a workspace folder, put the code at `legacy/<name>` (a copy or a symlink), or leave it where it is and pass `--source <path>` in step 2: preflight makes the `legacy/<name>` link for you and copies nothing. `<name>` is a short label: letters, digits, `-` and `_`.
2. **Run** `/code-modernization:modernize-preflight <name>` (add `--source /path/to/code` if it lives elsewhere).
3. **Follow the "next step" line** each command ends with, or run `/code-modernization:modernize-status <name>` at any time: it says where you are and gives the exact command to paste.

Commands are namespaced, so type the full name (autocomplete finds it from `/modernize`). Flags go after the arguments. No command edits your code: they write to `analysis/<name>/` and `modernized/`, and each refreshes `analysis/<name>/REPORT.html`, one page with everything found so far that you can open or share.

## The path

Each step stands alone, so you can stop and review after any of them.

| Step | Command | What you get |
| --- | --- | --- |
| 1 | `modernize-preflight <name> [target-stack]` | Is the environment ready? Asks the five questions only a person can answer, checks tools and a real build, finds missing source, and says what to fix. `PREFLIGHT.md` |
| 2 | `modernize-assess <name>` | What am I dealing with: inventory, complexity, debt, security, and the recommended pattern. `ASSESSMENT.md` |
| 3 | `modernize-map <name>` | The structure: dependencies, data flow, entry points and business flows as an interactive map (`TOPOLOGY.html`). Takes an existing dependency graph with `--graph <file>`. |
| 4 | `modernize-extract-rules <name>` | The business rules as testable Given/When/Then cards with `file:line` citations, each checked by a second agent. `BUSINESS_RULES.md` |
| 5 | `modernize-brief <name> [target-stack]` | The phased plan a steering committee approves. Nothing is built until you approve it. `MODERNIZATION_BRIEF.md` |
| 6 | one of `uplift`, `transform`, `reimagine` | The build. See below. |
| 7 | `modernize-harden <name>` | A security scan of the still-running legacy system, with ranked findings and a reviewed patch you apply yourself. `SECURITY_FINDINGS.md` |

`assess --portfolio <parent-dir>` ranks many systems into a sequencing heat-map.

## Choose how to build (the brief recommends one)

| If you want | Run | What happens |
| --- | --- | --- |
| The same language on a newer version (.NET Framework 4.8 to .NET 8, Java 8 to 17, Spring Boot 2 to 3) | `modernize-uplift <name> <from> <to>` | Keeps your code and fixes only what the new version breaks, driven by a catalog of the breaking changes this code actually hits. One pilot unit first and its lessons written down, then batches. Proves nothing changed by running the test suite on both versions where both can run. |
| A new stack, one module at a time, while the old system keeps running | `modernize-transform <name> [module] [target-stack]` | A plan you approve, tests that pin the old behavior, an idiomatic rewrite, and proof: the tests are run, counted, and shown to fail when the code is deliberately broken. |
| A rebuild on a new architecture | `modernize-reimagine <name> <vision>` | A spec mined from the code, an architecture that is reviewed and approved, then services scaffolded with executable acceptance tests. |

If the delta catalog shows an "uplift" would rewrite most of the code, the command says so and points to `transform`.

## Set it up so it runs smoothly

The commands never edit your code, by convention. A `.claude/settings.json` in the workspace backs that up with a deny rule for the source and allow rules for the outputs (`preflight` checks for the deny rule):

```json
{
  "permissions": {
    "allow": ["Read(**)", "Edit(analysis/**)", "Edit(modernized/**)"],
    "deny": ["Edit(/legacy/**)"]
  }
}
```

- File writes are matched through the `Edit` rule, so this covers the `Write` tool too (a `Write(path)` rule is never consulted). The leading `/` anchors the rule at the workspace root.
- If `legacy/<name>` is a symlink (which `--source` makes), also allow reading its target (`"additionalDirectories": ["/path/to/code"]`) and deny its real path (`"Edit(//path/to/code/**)"`), because the rule above matches the link's path, not its target's.
- The rule covers Claude's file tools and the shell commands it recognizes. A script that opens files itself is not covered, so keep Bash on a *prompted* permission mode for the two steps that fan out many writing agents at once (`uplift` step 5b and `reimagine` phase E).
- Shell commands still ask even in accept-edits mode (`python3` scripts, `scc`, `rsync`, your build and test commands, anything outside the workspace). Use accept-edits mode or allow rules for the ones you trust.

Helpful but optional (run `preflight` to check them all): [`scc`](https://github.com/boyter/scc) or `cloc` for size metrics; `python3` for the map, the shard builder and the report; a build toolchain for your stack, which enables the strongest equivalence proof (running old and new side by side); and the whole system in the tree (deployment descriptors, copybooks, DDL), which entry points and data lineage need. Without a toolchain the plugin falls back to recorded-output tests and says so.

## Safety

- **Analyzed code is untrusted input.** A hostile codebase can plant comments like "ignore previous instructions" to steer what lands in `BUSINESS_RULES.md` or `SECURITY_FINDINGS.md`. Agents treat file content as data and flag instruction-shaped text, verification agents re-derive every rule and finding from the cited code, and `brief` is a human approval gate before anything is built. Treat discovery artifacts from untrusted code with the same skepticism as the code.
- **Secrets stay out of shared artifacts.** Discovered credentials are masked (`AKIA****`) and inventoried in a gitignored `SECRETS.local.md` (or `~/.modernize/<name>/` outside git); `harden` keeps credential-removal hunks in a separate gitignored patch. `--show-secrets` puts raw values in the quarantine file only.
- **Trying it on a live repository.** `preflight` and `assess` change no source file. Preflight's smoke test compiles one file and, where there is a build system, restores and builds one small project, which writes build output wherever the build normally does.

## Working in a team

State lives in files, not in chat: later commands read the brief and `PREFLIGHT.md`, not your conversation, so a second person or a fresh session can run `status` and continue. The commands never commit, so commit `analysis/` and `modernized/` yourself.

| Artifact | Suggested reviewer |
| --- | --- |
| `PREFLIGHT.md` (the five answers, scope boundary, build checks) | whoever owns the build |
| `ASSESSMENT.md`, `REPORT.html` | the engineering lead or sponsor |
| `topology.json`, `TOPOLOGY.html` | engineers who know the system |
| `BUSINESS_RULES.md` | a business expert per domain: start with the P0 rules and the closing question list |
| `MODERNIZATION_BRIEF.md` | the approver, who steers execution by editing it |
| `SECURITY_FINDINGS.md` and the patch | a security engineer, who applies the patch |

## Live progress pane (early access)

A pane beside the transcript that shows the map of your code, how far each part has got and what to run next, in any language and for any of the three ways of building. It needs Claude Code's early-access function hooks: start with `CLAUDE_CODE_ENABLE_FUNCTION_HOOKS=1 claude`. Without the flag nothing changes. Details are in [hooks/README.md](hooks/README.md).

## Good to know

- **The assessment's COCOMO figure is a relative size index, never a timeline or a cost.** Its constants encode human-team productivity, which agentic work does not follow.
- **A model does the extraction, so two runs can find different rules.** Treat `BUSINESS_RULES.md` as reviewed output, not a deterministic build artifact. Headings are always `### RULE-NNN: <name>`.
- **Large runs are resumable.** On Claude Code builds with the Workflow tool, `extract-rules`, `harden`, `assess --portfolio`, `reimagine` and `uplift` run as scripted multi-agent jobs that verify findings adversarially. `extract-rules` shards by module and asks before a big run; a stopped run resumes in the same session with its run ID, and finished agents replay from the journal. `uplift` migrates in escalating batches behind a circuit breaker. Older builds fall back to plain subagents automatically.
- **Adapting it.** Commands, agents and workflows are markdown and JavaScript under Apache 2.0: fork them to change the prompts or steps for your stack.
- **Agents.** `legacy-analyst`, `business-rules-extractor`, `architecture-critic`, `security-auditor`, `test-engineer`, `version-delta-analyst`, `uplift-migrator` and `scaffolder` are invoked by the commands (or directly). The last two write only inside their own unit's directory.
- **Related.** [code-migration-kit-with-claude-code](https://github.com/anthropics/code-migration-kit-with-claude-code) is a separate public kit of prompts, templates and scripts for large-scale language migrations. This plugin is the guided, command-driven workflow from discovery through plan, build and proof; use either or both.

## License

Apache 2.0. See `LICENSE`.
