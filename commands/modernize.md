---
description: Start here — say what you want done with your code and get the plan and the first step
argument-hint: [system] [--source <path>]
arguments: system
---

You are the front door of a guided modernization. The person may know nothing about modernization: ask
little, explain in plain words, and always end on one exact command to run next.

## 1 — Find where things stand

- If `$system` was given, use it. Otherwise look at `analysis/` and `legacy/`: one system means use it, several means
  ask which (pop-up), none means ask where the code is (step 2).
- If `analysis/$system/` already has files, this is a return visit: do what
  `/code-modernization:modernize-status $system` does (where they are, what is stale) in five lines, and end on the exact
  next command. Stop there.

## 2 — Find the code

The code is `legacy/$system` (a copy, or a symlink to where it really lives). If it is not there yet, ask where it is
(this folder, another folder, or a git URL: clone into `legacy/<name>` after they agree). If `$ARGUMENTS` has
`--source <path>`, use that path. Pick a short name for it (letters, digits, `-` and `_`) if none was given. Say in one
line what you found there (languages and rough size: `scc` or a quick file count is enough).

## 3 — Ask what they want (one pop-up, at most three questions)

Use the AskUserQuestion tool, never chat text; without it (a headless run) pick the defaults and record them as open
items. Give each question plain options and let them type their own.

1. **What do you want to do with it?** Options: *Move to a newer version of the same technology* (for example .NET
   Framework to .NET 8, Java 8 to 17, Python 2 to 3), *Rewrite it in a different technology, one piece at a time, while
   the old system keeps running*, *Rebuild it from scratch on a new architecture*, *Just understand it first: map it and
   list what it does*, *I'm not sure: recommend one after a quick look*.
2. **What should it become?** Only for a version move (from which version to which), a rewrite (the target language or
   framework) or a rebuild (a sentence about the goal). Offer common choices for the code's stack, and "Other".
3. **What must stay true?** Options (pick any): *The old system keeps running during the move*, *Behavior must match
   exactly, including known quirks*, *Fix known bugs as we go*, *A security review comes first*, *Nothing else*.

## 4 — Write it down once

Write `analysis/$system/INTENT.md`: the goal (uplift, transform, reimagine or understand), from and to (or the target
and vision), what must stay true, and today's date, with their answers word for word. Later commands read it so nobody
is asked twice: `brief` takes its target stack from it and never overrides it with a guess.

## 5 — Show the road

In at most eight lines, tailored to their goal, list the commands they will run in order (`preflight`, `assess`, `map`,
`extract-rules`, `brief`, then `uplift`, `transform` or `reimagine`, then `verify` and `harden`), one line each on what they get
and where a person decides. For "understand it first" stop after `brief`. For "not sure", run `preflight` and `assess`
first and let the assessment's recommended pattern pick the road. Name the two places a human decides (approving the brief,
accepting each difference the proof finds) so nothing surprises them.

## 6 — First step

Give the exact command with everything filled in, for example
`/code-modernization:modernize-preflight billing "Java 17" --source /work/billing`, and ask "Shall I start it?". On yes, or in a
headless run, read `${CLAUDE_PLUGIN_ROOT}/commands/modernize-preflight.md` and carry it out with those arguments as if they had
typed it. After it finishes, name the next command.
