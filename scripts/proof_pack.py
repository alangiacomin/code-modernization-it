#!/usr/bin/env python3
"""Independent proof pack: one plain verdict per built module, computed from the evidence files.

    python3 proof_pack.py <system> [module] [--workspace DIR]

Writes analysis/<system>/VERIFICATION.md (for people) and VERIFICATION.json (for the report). The
verdict is computed here by fixed rules, never by a model's opinion, and every rule is written into
the output so an auditor can follow it:

  PROVEN         all six checks below pass.
  NOT PROVEN     any check fails: nothing executed, a test failed, an equivalence case differs or is
                 missing, a baseline regression or new failure, a deliberate break that no test noticed.
  PARTLY PROVEN  nothing failed, but at least one check could not be passed; each is listed.

  1  Tests ran         at least one test executed in a fresh run, none failed, none was skipped
                       without a reason, and every result file is newer than the code. The counts must
                       come from files this script parsed itself: JUnit-style XML, or a saved raw runner
                       log (Maven/Gradle, cargo, pytest, unittest, go test, dotnet test, jest, vitest,
                       ctest, phpunit). Counts only typed into test-runs.json cap the check at "gap".
  2  Rules traced      rewrite and reimagine only: every P0 rule the module answers for is named by a
                       test (an id in a test name or comment). A rule only the notes name is "claimed",
                       not tested. Uplifts keep the code, so they trace no rules.
  3  Same behavior     the development cases, judged again here by compare.py, executed at least one
                       case with none differing or missing (a case a person approved is allowed and
                       listed); for an uplift, baseline_diff.py may stand in: no regression, no new
                       failure, no missing test or module, no drop in executed tests.
  4  Fresh inputs      at least 10 new inputs, none with the same output as a development case, ran on
                       the legacy and the new code and compare.py finds no difference. Needed whenever
                       the legacy could run here; when it could not, the proof rests on recorded
                       traces and the best possible verdict is PARTLY PROVEN.
  5  Canary            a deliberate one-line break whose own result file or saved runner log, parsed
                       here, shows failing tests. A "Canary:" line in the notes is a claim, not evidence.
  6  Source untouched  no file under legacy/<system> is newer than the analysis (PREFLIGHT.md); a plain
                       file walk, no version-control tool is run inside the untrusted tree.

Open questions, unticked criteria and the sign-off are for a person: they never change the verdict.

Evidence read (under analysis/<system>/, or as named): equivalence/test-runs.json (written by the
modernize-verify command), equivalence/[<module>/]cases.json and fresh-cases.json (judged again here,
not read from EQUIVALENCE.json), BASELINE.md, BUSINESS_RULES.md with the code under modernized/,
MODERNIZATION_BRIEF.md, the notes files, and legacy/<system>. Everything read is untrusted text: it is
never run, links out of the workspace are refused, sizes are capped. Exit 0 when every verdict is
PROVEN, 1 when not, 2 for input that cannot be used.
"""
import argparse
import datetime
import json
import os
import re
import stat
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.dont_write_bytecode = True          # importing the sibling scripts must not leave __pycache__ in the plugin folder
sys.path.insert(0, HERE)
import baseline_diff  # noqa: E402
import compare  # noqa: E402
import trace_rules  # noqa: E402

FRESH_MIN, LIST_CAP, JSON_CAP = 10, 40, 8 << 20
VERDICTS = ("PROVEN", "PARTLY PROVEN", "NOT PROVEN")
CHECKS = (("tests", "Tests ran"), ("rules", "Rules traced"), ("same", "Same behavior"), ("fresh", "Fresh inputs"),
          ("canary", "Canary"), ("source", "Source untouched"))
RULES_TEXT = (
    "PROVEN needs all six checks to pass. NOT PROVEN when any check fails. PARTLY PROVEN when nothing failed but a check could not pass.",
    "1. Tests ran: at least one test executed in a fresh run, none failed, none was skipped without a reason, and every result file is newer than the code. "
    "The counts must be read by this script from result files or a saved raw runner log; counts only typed in cannot reach PROVEN.",
    "2. Rules traced (rewrite and reimagine): every P0 rule the module answers for is named by at least one test. A rule that only the notes name is claimed, not tested.",
    "3. Same behavior: the development cases, judged again by compare.py, executed at least one case and none differs or is missing (a difference a person approved is allowed and listed); "
    "for an uplift, no regression, no new failure, no missing test and no drop in executed tests against BASELINE.md.",
    "4. Fresh inputs: at least 10 new inputs, none with the same output as a development case, ran on the legacy and the new code with no difference. Needed whenever the legacy could run here; "
    "when it could not, the proof is trace-based and the best verdict is PARTLY PROVEN.",
    "5. Canary: a deliberate one-line break whose own result file or saved runner log shows failing tests. A line in the notes is a claim.",
    "6. Source untouched: no file under legacy/<system> is newer than the analysis (PREFLIGHT.md), by a plain file walk; no version-control tool is run.",
    "Open questions, unticked criteria and the sign-off are for a person. They never change the verdict.",
)
WORDS = {"pass": "pass", "gap": "not proven", "fail": "FAIL", "na": "not applicable"}
CANARY = re.compile(r"Canary[^:\n|]{0,20}:\s*(.{1,300}?)\s*(?:→|->|=>|,)\s*(\d[\d,]*)\s+tests?\s+(?:failed|went red|failing)", re.I)
CHECKBOX = re.compile(r"^\s*[-*]\s*\[( |x|X)\]\s*(.*)$")
NOTE_NAMES = trace_rules.NOTES_NAMES
clean = trace_rules.clean


class InputError(Exception):
    pass


# ---------------------------------------------------------------- reading evidence safely
def read_json(path, cap=8 << 20):
    """-> (value, problem). A missing file is (None, None); a link, a huge file or bad JSON is (None, reason)."""
    try:
        st = os.lstat(path)
    except OSError:
        return None, None
    name = clean(os.path.basename(path), 80)
    if not stat.S_ISREG(st.st_mode):
        return None, "%s is a link or not a regular file, so it was not read" % name
    if st.st_size > cap:
        return None, "%s is larger than %d MB, so it was not read" % (name, cap >> 20)
    try:
        with open(path, "rb") as fh:
            return json.loads(fh.read().decode("utf-8-sig")), None
    except (OSError, ValueError, RecursionError) as err:
        return None, "%s could not be read as JSON (%s)" % (name, clean(str(err), 80))


def read_text(path, cap=8 << 20):
    """Text of a regular, non-binary file, or None."""
    return trace_rules.read_text(path, cap) if os.path.isfile(path) and not os.path.islink(path) else None


def nint(value):
    return value if isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= 10 ** 9 else None


def inside(workspace, rel):
    """The real path of `rel` when it stays inside the workspace, else None (absolute paths and links out are refused)."""
    if not isinstance(rel, str) or not rel or "\x00" in rel:
        return None
    real = os.path.realpath(rel if os.path.isabs(rel) else os.path.join(workspace, rel))
    root = os.path.realpath(workspace)
    try:
        return real if os.path.commonpath([root, real]) == root else None
    except ValueError:
        return None


# ---------------------------------------------------------------- test-runs.json
def load_test_runs(adir):
    """-> the validated content of equivalence/test-runs.json (everything defaulted when it is absent or malformed)."""
    obj, problem = read_json(os.path.join(adir, "equivalence", "test-runs.json"))
    out = {"present": isinstance(obj, dict), "problems": [problem] if problem else [], "date": "", "legacy": {"ran": None, "how": "", "why": ""}, "suites": [], "canaries": [], "leftOut": []}
    if not isinstance(obj, dict):
        if obj is not None:
            out["problems"].append("test-runs.json is not a JSON object, so it was not used.")
        return out
    out["date"] = clean(obj.get("date"), 40)
    out["leftOut"] = [clean(v, 200) for v in (obj.get("leftOut") if isinstance(obj.get("leftOut"), list) else [])[:20] if isinstance(v, str) and v.strip()]
    lg = obj.get("legacy") if isinstance(obj.get("legacy"), dict) else {}
    out["legacy"] = {"ran": lg.get("ran") if isinstance(lg.get("ran"), bool) else None, "how": clean(lg.get("how"), 300), "why": clean(lg.get("why"), 300)}
    for s in (obj.get("suites") if isinstance(obj.get("suites"), list) else [])[:200]:
        if isinstance(s, dict):
            out["suites"].append({"module": clean(s.get("module"), 100), "name": clean(s.get("name"), 120), "command": clean(s.get("command"), 300), "date": clean(s.get("date"), 40),
                                  "executed": nint(s.get("executed")), "failed": nint(s.get("failed")), "skipped": nint(s.get("skipped")),
                                  "skippedReason": clean(s.get("skippedReason"), 300), "note": clean(s.get("note"), 300), "junit": paths_of(s.get("junit")), "log": paths_of(s.get("log"))})
    for c in (obj.get("canaries") if isinstance(obj.get("canaries"), list) else [])[:50]:
        if isinstance(c, dict):
            out["canaries"].append({"module": clean(c.get("module"), 100), "change": clean(c.get("change"), 300), "testsFailed": nint(c.get("testsFailed")),
                                    "junit": paths_of(c.get("junit")), "log": paths_of(c.get("log"))})
    return out


def paths_of(value):
    """A list of path strings from a string or a list, however malformed."""
    return [v for v in (value if isinstance(value, list) else [value])[:20] if isinstance(v, str) and v]


def suites_for(runs, subject, unit, subjects):
    """The suites that belong to one subject. A suite that names no module belongs to the only subject."""
    others = {s["name"].lower() for s in subjects if s["track"] != "uplift"}
    out = []
    for s in runs["suites"]:
        mod = s["module"].lower()
        if not mod:
            ok = len(subjects) == 1
        elif subject["track"] == "uplift":       # one uplifted working copy holds many units; a unit argument narrows it
            ok = mod not in others and (not unit or mod == unit.lower() or mod == subject["name"].lower())
        else:
            ok = mod == subject["name"].lower()
        if ok:
            out.append(s)
    return out


def code_mtime(root):
    """Newest modification time among a module's code (no build output, hidden files or documents)."""
    newest = 0.0
    for base, dirs, names in os.walk(root):
        dirs[:] = [d for d in dirs if not d.startswith(".") and d not in trace_rules.SKIP_DIRS and not os.path.islink(os.path.join(base, d))]
        for n in names:
            full = os.path.join(base, n)
            if n.startswith(".") or os.path.splitext(n)[1].lower() in trace_rules.DOC_EXT:
                continue
            try:
                st = os.lstat(full)
            except OSError:
                continue
            if stat.S_ISREG(st.st_mode):
                newest = max(newest, st.st_mtime)
    return newest


# ---------------------------------------------------------------- raw runner logs
LOG_CAP, LOG_LINE = 16 << 20, 2000
NUM_WORD = re.compile(r"(\d+)\s+([A-Za-z]+)")


def words(text):
    """{'passed': 10, 'failed': 2} from '2 failed, 10 passed' style text."""
    out = {}
    for n, w in NUM_WORD.findall(text[:LOG_LINE]):
        out[w.lower()] = out.get(w.lower(), 0) + int(n)
    return out


def _maven(m):
    run, f, e, sk = (int(g) for g in m.groups())
    return max(0, run - f - e - sk), f + e, sk


def _pytest(m):
    w = words(m.group(1))
    return w.get("passed", 0) + w.get("xpassed", 0) + w.get("xfailed", 0), w.get("failed", 0) + w.get("error", 0) + w.get("errors", 0), w.get("skipped", 0)


def _jest(m):
    w = words(m.group(1))
    return w.get("passed", 0), w.get("failed", 0), w.get("skipped", 0)


def _php(m):
    w = {k.lower(): int(v) for k, v in re.findall(r"([A-Za-z]+):\s*(\d+)", m.group(1)[:LOG_LINE])}
    failed, skipped = w.get("failures", 0) + w.get("errors", 0), w.get("skipped", 0) + w.get("incomplete", 0)
    return max(0, w.get("tests", 0) - failed - skipped), failed, skipped


def _ctest(m):
    failed, total = int(m.group(1)), int(m.group(2))
    return max(0, total - failed), failed, 0


def _gradle(m):
    total, failed, skipped = int(m.group(1)), int(m.group(2) or 0), int(m.group(3) or 0)
    return max(0, total - failed - skipped), failed, skipped


# runner, a line pattern, and how to read (passed, failed, skipped) from a match. Every pattern is anchored and bounded.
LOG_LINES = (
    ("maven", re.compile(r"^(?:\[\w+\]\s*)?Tests run: (\d+), Failures: (\d+), Errors: (\d+), Skipped: (\d+)\s*$"), _maven),
    ("gradle", re.compile(r"^(\d+) tests? completed(?:, (\d+) failed)?(?:, (\d+) skipped)?\s*$"), _gradle),
    ("cargo", re.compile(r"^test result: (?:ok|FAILED)\. (\d+) passed; (\d+) failed; (\d+) ignored;"), lambda m: (int(m.group(1)), int(m.group(2)), int(m.group(3)))),
    ("pytest", re.compile(r"^(?:=+ )?((?:\d+ [a-z]+(?:, )?)+) in [\d.]+s(?: \([\d:]+\))?(?: =+)?\s*$"), _pytest),
    ("pytest", re.compile(r"^(?:=+ )?no tests ran in [\d.]+s"), lambda m: (0, 0, 0)),
    ("go test", re.compile(r"^\s*--- (PASS|FAIL|SKIP): \S"), lambda m: {"PASS": (1, 0, 0), "FAIL": (0, 1, 0), "SKIP": (0, 0, 1)}[m.group(1)]),
    ("go test -json", re.compile(r'^\{.*"Action":"(pass|fail|skip)".*"Test":"[^"]+"'), lambda m: {"pass": (1, 0, 0), "fail": (0, 1, 0), "skip": (0, 0, 1)}[m.group(1)]),
    ("dotnet test", re.compile(r"^(?:Passed|Failed)!\s+-\s+Failed:\s+(\d+),\s+Passed:\s+(\d+),\s+Skipped:\s+(\d+)"), lambda m: (int(m.group(2)), int(m.group(1)), int(m.group(3)))),
    ("jest", re.compile(r"^\s*Tests:\s+(.*\b\d+ total)\s*$"), _jest),
    ("vitest", re.compile(r"^\s*Tests\s{2,}(.*)\(\d+\)\s*$"), _jest),
    ("ctest", re.compile(r"^\d+% tests passed, (\d+) tests? failed out of (\d+)"), _ctest),
    ("phpunit", re.compile(r"^OK \((\d+) tests?, \d+ assertions?\)"), lambda m: (int(m.group(1)), 0, 0)),
    ("phpunit", re.compile(r"^(Tests: \d+, Assertions: \d+.*?)\.?\s*$"), _php),
)
UNITTEST_RAN = re.compile(r"^Ran (\d+) tests? in [\d.]+s\s*$")
UNITTEST_END = re.compile(r"^(?:OK|FAILED)(?: \(([^)]*)\))?\s*$")


def parse_runner_log(text):
    """(executed, failed, skipped, runners) from the runner's own summary lines, summed over the log; None when no line is recognised.
    Recognised: Maven/Gradle, cargo, pytest, unittest, go test (-v or -json), dotnet test, jest, vitest, ctest, phpunit."""
    passed = failed = skipped = 0
    seen, ran = [], None
    for line in text.split("\n")[:3000000]:
        line = line.rstrip("\r")[:LOG_LINE]
        if ran is not None and line.strip():
            m = UNITTEST_END.match(line)
            if m:
                w = {k: int(v) for k, v in re.findall(r"(\w+)=(\d+)", (m.group(1) or "")[:LOG_LINE])}
                f, sk = w.get("failures", 0) + w.get("errors", 0), w.get("skipped", 0)
                passed, failed, skipped = passed + max(0, ran - f - sk), failed + f, skipped + sk
                seen.append("unittest")
            ran = None
        m = UNITTEST_RAN.match(line)
        if m:
            ran = int(m.group(1))
            continue
        for name, rx, read in LOG_LINES:
            m = rx.match(line)
            if m:
                p, f, sk = read(m)
                passed, failed, skipped = passed + p, failed + f, skipped + sk
                seen.append(name)
                break
    return (passed + failed, failed, skipped, sorted(set(seen))) if seen else None


def read_logs(paths):
    """Saved runner logs -> {"files", "executed", "failed", "skipped", "runners", "oldest", "newest", "unrecognised"}. A log without a summary line of a known runner is no evidence."""
    out = {"files": 0, "executed": 0, "failed": 0, "skipped": 0, "runners": [], "oldest": None, "newest": None, "unrecognised": []}
    for path in paths:
        try:
            st = os.lstat(path)
            if not stat.S_ISREG(st.st_mode) or st.st_size > LOG_CAP:
                out["unrecognised"].append("%s (a link, not a file, or larger than %d MB)" % (clean(os.path.basename(path), 80), LOG_CAP >> 20))
                continue
            with open(path, "rb") as fh:
                got = parse_runner_log(fh.read(LOG_CAP).decode("utf-8", "replace"))
        except OSError:
            out["unrecognised"].append("%s (could not be read)" % clean(os.path.basename(path), 80))
            continue
        if got is None:
            out["unrecognised"].append("%s (no summary line of a runner this script knows)" % clean(os.path.basename(path), 80))
            continue
        out["files"] += 1
        out["executed"], out["failed"], out["skipped"] = out["executed"] + got[0], out["failed"] + got[1], out["skipped"] + got[2]
        out["runners"] = sorted(set(out["runners"]) | set(got[3]))
        out["oldest"] = st.st_mtime if out["oldest"] is None else min(out["oldest"], st.st_mtime)
        out["newest"] = st.st_mtime if out["newest"] is None else max(out["newest"], st.st_mtime)
    return out


def utc(ts):
    return datetime.datetime.fromtimestamp(ts or 0, datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def suite_evidence(suite, workspace):
    """-> (counts for one suite, its parsed JUnit-style results or None). Evidence, best first: result files, a saved raw runner log,
    and only then the counts the command typed, which are never enough for PROVEN."""
    ev = {"name": suite["name"], "command": suite["command"], "date": suite["date"], "note": suite["note"], "notes": [], "source": "reported" if suite["executed"] is not None else "none",
          "files": 0, "newest": None, "oldest": None, "written": "", "executed": suite["executed"] or 0, "failed": suite["failed"] or 0, "skipped": suite["skipped"] or 0,
          "skippedNoReason": (suite["skipped"] or 0) if not suite["skippedReason"] else 0}
    said = {"executed": suite["executed"], "failed": suite["failed"], "skipped": suite["skipped"]}
    junit = [(j, inside(workspace, j)) for j in suite["junit"]]
    logs = [(j, inside(workspace, j)) for j in suite["log"]]
    ev["notes"] += ["%s is outside the workspace, so it was not read" % clean(j, 100) for j, p in junit + logs if p is None]

    def mismatch(mine):
        for label, value in mine.items():
            if said[label] is not None and said[label] != value:
                ev["notes"].append("the suite reported %d %s but the files show %d; the files were used" % (said[label], label, value))

    good = [p for _, p in junit if p]
    if good:
        fresh = baseline_diff.read_results(good)
        ev["notes"] += ["result file not used: " + u for u in fresh["unreadable"][:3]]
        if fresh["files"]:
            c = baseline_diff.tally(fresh["tests"].values())
            ev.update({"source": "result files", "files": fresh["files"], "newest": fresh["newest"], "oldest": fresh["oldest"], "written": utc(fresh["newest"]), "executed": c["executed"],
                       "failed": c["fail"] + c["error"], "skipped": c["skip"],
                       "skippedNoReason": 0 if suite["skippedReason"] else sum(1 for t, st in fresh["tests"].items() if st == "SKIP" and not fresh["skipReasons"].get(t))})
            mismatch({"executed": ev["executed"], "failed": ev["failed"], "skipped": ev["skipped"]})
            return ev, fresh
        ev["notes"].append("no readable result file was found under %s" % ", ".join(clean(j, 100) for j, p in junit if p))
    good = [p for _, p in logs if p]
    if good:
        got = read_logs(good)
        ev["notes"] += ["log not used: " + u for u in got["unrecognised"][:3]]
        if got["files"]:
            ev.update({"source": "runner log", "files": got["files"], "newest": got["newest"], "oldest": got["oldest"], "written": utc(got["newest"]), "executed": got["executed"],
                       "failed": got["failed"], "skipped": got["skipped"], "skippedNoReason": 0 if suite["skippedReason"] else got["skipped"]})
            ev["notes"].append("counts read from the summary lines of %s" % ", ".join(got["runners"]))
            mismatch({"executed": ev["executed"], "failed": ev["failed"], "skipped": ev["skipped"]})
    return ev, None


# ---------------------------------------------------------------- the source check
SOURCE_CAP, EXAMPLES = 400000, 20
NO_VCS = "by modification time, and no version-control tool was run"


def reference_time(adir):
    """When the analysis began: the modification time of PREFLIGHT.md, else that of the oldest file in analysis/<system>/."""
    def mtime(path):
        try:
            st = os.lstat(path)
            return st.st_mtime if stat.S_ISREG(st.st_mode) else None
        except OSError:
            return None
    ref = mtime(os.path.join(adir, "PREFLIGHT.md"))
    if ref is not None:
        return ref
    try:
        times = [t for t in (mtime(os.path.join(adir, n)) for n in os.listdir(adir)) if t is not None]
    except OSError:
        return None
    return min(times) if times else None


def source_check(workspace, system, adir):
    """-> {"state": clean|changed|unknown, "method", "detail", "files", "path", "target"} for legacy/<system>.
    A plain file walk, never following a link and never running a program in the tree: any regular file newer than the
    analysis is reported as changed. A walk that cannot finish is "not checked", never "untouched"."""
    link = os.path.join(workspace, "legacy", system)
    target = os.path.realpath(link) if os.path.lexists(link) else ""
    out = {"state": "unknown", "method": NO_VCS, "detail": "", "files": [], "path": "legacy/" + system, "target": clean(target if os.path.islink(link) else "", 300)}
    if not target or not os.path.isdir(target):
        out["detail"] = "legacy/%s was not found, so it was not checked" % system
        return out
    ref = reference_time(adir)
    if ref is None:
        out["detail"] = "there is no PREFLIGHT.md or other analysis file to date the analysis by, so legacy/%s was not checked" % system
        return out
    newer, seen, unreadable = [], 0, [0]

    def failed(_err):
        unreadable[0] += 1

    for base, dirs, names in os.walk(target, onerror=failed, followlinks=False):
        dirs[:] = [d for d in dirs if d != ".git" and not os.path.islink(os.path.join(base, d))]
        for n in names:
            seen += 1
            if seen > SOURCE_CAP:
                break
            full = os.path.join(base, n)
            try:
                st = os.lstat(full)
            except OSError:
                unreadable[0] += 1
                continue
            if stat.S_ISREG(st.st_mode) and st.st_mtime > ref:
                newer.append(clean(os.path.relpath(full, target), 200))
        if seen > SOURCE_CAP:
            break
    out["files"] = newer[:EXAMPLES]
    if seen > SOURCE_CAP or unreadable[0]:
        out["detail"] = "the walk could not finish (%s), so legacy/%s was not fully checked" % ("more than %d files" % SOURCE_CAP if seen > SOURCE_CAP else "%d path(s) could not be read" % unreadable[0], system)
        out["state"] = "changed" if newer else "unknown"
        if newer:
            out["detail"] = "%d file(s) changed after the analysis started, and the walk could not finish" % len(newer)
        return out
    out["state"] = "changed" if newer else "clean"
    out["detail"] = ("%d file(s) changed after the analysis started" % len(newer)) if newer else "no file changed after the analysis started (%d files compared)" % seen
    return out


# ---------------------------------------------------------------- the brief
def brief_items(text, module, track):
    """Unticked criteria a person decides: the exit criteria of the module's phase, and the open questions of section 7."""
    if not text:
        return {"found": False, "phase": "", "items": [], "count": 0}
    lines = [ln[:2000] for ln in text.split("\n")]
    phases, cur = [], None
    for line in lines:
        m = re.match(r"#{2,5}\s+Phase\s+(\d+)\b", line)
        if m:
            cur = {"n": int(m.group(1)), "title": clean(re.split(r"\s[—-]\s", line.lstrip("# "))[0], 60), "command": "", "modules": set(), "exit": [], "in_exit": False}
            phases.append(cur)
        elif re.match(r"#{1,3}\s", line):
            cur = None
        elif cur is not None:
            k = re.match(r"\s*(Command|Modules)\s*:\s*(.*)$", line)
            if k and k.group(1) == "Command":
                cur["command"] = k.group(2).lower()
            elif k:
                cur["modules"] = {t.strip().lower() for t in re.split(r"[,;]", k.group(2)) if t.strip()}
            elif re.match(r"\s*Exit criteria\s*:", line):
                cur["in_exit"] = True
            elif re.match(r"\s*(Entry criteria|Scale|Risk|Command|Modules)\s*:", line):
                cur["in_exit"] = False
            elif cur["in_exit"]:
                c = CHECKBOX.match(line)
                if c and c.group(1) == " ":
                    cur["exit"].append(clean(c.group(2), 300))
    verb = {"rewrite": "transform", "reimagine": "reimagine", "uplift": "uplift"}[track]
    by_name = [p for p in phases if module.lower() in p["modules"]] if track != "uplift" else []
    mine = by_name or [p for p in phases if verb in p["command"]]
    items = [{"text": t, "where": "%s exit criterion" % p["title"]} for p in mine for t in p["exit"]]
    phase_n = min((p["n"] for p in mine), default=None)
    level = None
    for line in lines:
        h = re.match(r"(#{1,3})\s+(.*)", line)
        if h:
            if re.match(r"(?:\d+[.)]?\s*)?open questions|7[.):\s]", h.group(2), re.I):
                level = len(h.group(1))
            elif level is not None and len(h.group(1)) <= level:
                level = None
            continue
        c = CHECKBOX.match(line) if level else None
        if c and c.group(1) == " ":
            tag = re.search(r"\[before Phase (\d+)\]", c.group(2), re.I)
            if not (tag and phase_n is not None and int(tag.group(1)) > phase_n):
                items.append({"text": clean(c.group(2).replace("**", ""), 300), "where": "open question, section 7"})
    return {"found": True, "phase": mine[0]["title"] if len(mine) == 1 else "", "items": items[:LIST_CAP], "count": len(items)}


# ---------------------------------------------------------------- the six checks
def row(cid, state, detail, **extra):
    r = {"id": cid, "label": dict(CHECKS)[cid], "state": state, "detail": clean(detail, 700)}
    r.update(extra)
    return r


def judge(path):
    """A cases file judged again with compare.py: (record or None, problem)."""
    if os.path.islink(path):
        return None, "%s is a link, so it was not read" % clean(os.path.basename(path), 80)
    try:
        return compare.run(path, None, False), None
    except compare.InputError as err:
        return None, clean(str(err), 200)
    except (OSError, ValueError, RecursionError, MemoryError) as err:
        return None, "the cases file could not be judged (%s)" % err.__class__.__name__


def mask_summary(records):
    """Fields the comparison ignored, grouped by the reason given for them: [{"why", "cases"}]."""
    groups = {}
    for r in records:
        for m in r["masked"]:
            why = re.search(r"\(([^()]*)\)\s*$", m)
            groups.setdefault(clean(why.group(1).strip() if why else "no reason given: " + m, 200), set()).add(r["id"])
    return [{"why": k, "cases": len(v)} for k, v in sorted(groups.items())][:10]


def tolerance_summary(records):
    """The declared numeric tolerances that were used, grouped: [{"why", "rel", "abs", "cases"}]. A tolerance is never silent."""
    groups = {}
    for r in records:
        if r.get("withinTolerance") and isinstance(r.get("tolerance"), dict):
            t = r["tolerance"]
            groups.setdefault((clean(t.get("why"), 200), t.get("rel"), t.get("abs")), set()).add(r["id"])
    return [{"why": k[0], "rel": k[1], "abs": k[2], "cases": len(v)} for k, v in sorted(groups.items(), key=lambda kv: str(kv[0]))][:10]


def summary_of(rec):
    t = rec["totals"]
    return {"cases": t["cases"], "executed": t["executed"], "same": t["same"], "differs": t["differs"], "missing": t["missing"], "selfCheck": rec["selfCheck"]["passed"],
            "withinTolerance": t.get("sameWithinTolerance", 0), "tolerances": tolerance_summary(rec["cases"]),
            "approved": [{"id": r["id"], "why": clean(r["approvedDifference"], 300)} for r in rec["cases"] if r["verdict"] == "differs-approved"][:LIST_CAP],
            "masks": mask_summary(rec["cases"]),
            "differing": [{"id": r["id"], "reason": clean(r["reason"], 300)} for r in rec["cases"] if r["verdict"] in ("differs", "missing")][:LIST_CAP]}


def cases_paths(adir, module, n_subjects):
    """The cases files of a module: its own folder equivalence/<module>/, else the shared equivalence/ folder."""
    for base, shared in ((os.path.join(adir, "equivalence", module), False), (os.path.join(adir, "equivalence"), True)):
        cases, fresh = os.path.join(base, "cases.json"), os.path.join(base, "fresh-cases.json")
        if os.path.lexists(cases) or os.path.lexists(fresh):
            return {"cases": cases if os.path.lexists(cases) else "", "fresh": fresh if os.path.lexists(fresh) else "", "shared": shared and n_subjects > 1}
    return {"cases": "", "fresh": "", "shared": False}


def recorded_matches(path, rec):
    """Does EQUIVALENCE.json on disk agree with what the cases say now? None when there is no usable file."""
    obj, _ = read_json(path)
    if not isinstance(obj, dict) or not isinstance(obj.get("totals"), dict):
        return None
    mine = rec["totals"]
    return all(obj["totals"].get(k) == mine[k] for k in ("cases", "executed", "same", "differs", "differsApproved", "missing"))


def check_tests(g, uplift, comparable):
    """Check 1. g: {executed, failed, skipped, skippedNoReason, suites, stale}. A suite's own note is added to the detail."""
    r = check_tests_state(g, uplift, comparable)
    notes = " ".join(e["note"] for e in g["suites"] if e.get("note"))
    if notes:
        r["detail"] = clean(r["detail"] + " Note: " + notes, 700)
    return r


def check_tests_state(g, uplift, comparable):
    ex, fail, skip, nr = g["executed"], g["failed"], g["skipped"], g["skippedNoReason"]
    if not g["suites"]:
        return row("tests", "fail", "No test run is recorded for this module, so nothing executed. Run its tests again and record them in equivalence/test-runs.json.")
    unread = [e["name"] or "a suite" for e in g["suites"] if e["source"] == "none"]
    if len(unread) == len(g["suites"]):
        return row("tests", "gap", "No test result could be read: no result file was parsed, no saved runner log has a summary line this script knows, and no counts were given (%s)." % "; ".join(n for e in g["suites"] for n in e["notes"][:2])[:300])
    if ex == 0:
        return row("tests", "fail", "Nothing executed: no test ran%s." % (" (%d were skipped)" % skip if skip else ""))
    if fail and not (uplift and comparable):
        return row("tests", "fail", "%d of %d executed test(s) failed." % (fail, ex))
    if nr and not (uplift and comparable):
        return row("tests", "gap", "%d test(s) were skipped with no reason given (%d executed, %d failed)." % (nr, ex, fail))
    if g["stale"]:
        return row("tests", "gap", "%d test(s) executed, but some result files are older than the code, so this was not a clean run of the current code: delete the build output and run the tests again." % ex)
    typed = [e["name"] or "a suite" for e in g["suites"] if e["source"] == "reported"]
    if unread or typed:
        return row("tests", "gap", "%d test(s) executed, but the counts for %s were typed in by the command, not read from a result file or a saved runner log, so this cannot be PROVEN." % (ex, ", ".join(unread + typed)))
    judged = " (failures are judged against the baseline below)" if fail and uplift else ""
    return row("tests", "pass", "%d test(s) executed, %d failed%s, %d skipped." % (ex, fail, judged, skip))


def check_rules(ctx, subject, evidence, caveats):
    """Check 2."""
    if subject["track"] == "uplift":
        return row("rules", "na", "An uplift keeps the code, so no business rule is traced. The baseline comparison stands in.")
    tr = ctx["trace"]
    if tr is None:
        return row("rules", "gap", ctx["trace_problem"])
    if not tr["rules"]:
        return row("rules", "gap", "BUSINESS_RULES.md has no rule cards in the form '### RULE-001: name', so no rule can be traced.")
    view = trace_rules.module_view(tr, subject["rel"])
    p0 = [r for r in view["rows"] if r["priority"] == "P0"]
    missing = [r["id"] for r in p0 if r["status"] != "tested"]
    evidence["rules"] = {"tied": view["tied"], "counted": len(view["rows"]), "outOfScope": view["outOfScope"], "totals": view["totals"], "p0NoTests": missing,
                         "p0": [{"id": r["id"], "name": r["name"], "confidence": r["confidence"], "status": r["status"], "main": r["main"], "tests": r["tests"], "claimed": r["claimed"],
                                 "where": clean((r["samples"]["tests"] or r["samples"]["main"] or [""])[0], 200)} for r in p0][:100]}
    if not view["tied"]:
        caveats.append("Nothing ties a rule to this module by name, so every rule in BUSINESS_RULES.md was counted.")
    if not p0:
        return row("rules", "pass", "No rule this module answers for is rated P0 (%d rule(s) counted)." % len(view["rows"]))
    if missing:
        claimed = sum(1 for r in p0 if r["status"] == "claimed only")
        return row("rules", "gap", "%d of %d P0 rule(s) are not named by any test: %s%s." % (len(missing), len(p0), ", ".join(missing[:12]), " (%d claimed only in the notes)" % claimed if claimed else ""))
    return row("rules", "pass", "All %d P0 rule(s) this module answers for are named by at least one test." % len(p0))


def baseline_state(ctx, suites, xml_paths, evidence, caveats, person):
    """The uplift's baseline comparison: (state, detail, whether it could compare)."""
    path = os.path.join(ctx["adir"], "BASELINE.md")
    if not os.path.isfile(path):
        return "gap", "BASELINE.md is missing: an uplift needs the old version's results recorded first (uplift, Step 4).", False
    if not xml_paths:
        return "gap", "BASELINE.md exists, but there are no result files to compare it with.", False
    try:
        b = baseline_diff.run(path, xml_paths)
    except baseline_diff.InputError as err:
        return "gap", clean(str(err), 300), False
    keys = ("ok", "regressionsCount", "newFailuresCount", "fixedCount", "missingCount", "missingModulesCount", "moduleDiffsCount", "renamed", "executedDrop", "skippedGrowth",
            "stillFailingCount", "newlySkippedCount", "flakyCount", "approvedCount")
    evidence["baseline"] = dict({k: b[k] for k in keys}, source=b["baseline"]["source"], targetOnly=b["baseline"]["targetOnly"], why=b["baseline"]["why"], before=b["baseline"]["counts"],
                                now=b["fresh"]["counts"], approved=b["approved"][:LIST_CAP], regressions=b["regressions"][:LIST_CAP], newFailures=b["newFailures"][:LIST_CAP], fixed=b["fixed"][:LIST_CAP], missing=b["missing"][:LIST_CAP])
    if b["fixedCount"]:
        person.append("%d test(s) failed on the old version and pass now. A person decides whether each is an intended fix." % b["fixedCount"])
    if b["flakyCount"]:
        caveats.append("%d test(s) the baseline lists as flaky flipped; they are not counted as regressions." % b["flakyCount"])
    if b["approvedCount"]:
        caveats.append("%d test difference(s) were approved by a person in BASELINE.md and are not counted: %s." % (
            b["approvedCount"], "; ".join("%s (%s)" % (clean(x["id"], 80), clean(x["reason"] or "no reason given", 80)) for x in b["approved"][:5])))
    if b["baseline"]["targetOnly"] or not b["baseline"]["counts"]:
        return "gap", "The baseline says target-only (%s): the old version did not run here, so there is nothing to compare with." % (b["baseline"]["why"] or "no reason given"), False
    if b["renamed"]:
        caveats.append("%d test name(s) changed while their class did not get worse (parameterized names that embed a path, for example); they were not counted as missing." % b["renamed"])
    if b["regressionsCount"] or b["newFailuresCount"]:
        hint = " Tests the baseline never listed were added after it was recorded: run them on the old version too and add them to BASELINE.md to tell a regression from a test that was never green." if b["newFailuresCount"] else ""
        return "fail", "%d test(s) passed before and fail now; %d test(s) the baseline never listed (or skipped) fail now.%s" % (b["regressionsCount"], b["newFailuresCount"], hint), True
    gaps = ["%d %s" % (n, what) for n, what in ((b["missingCount"], "baseline test(s) did not run now"), (b["missingModulesCount"], "baseline module(s) are missing from the results"),
                                                   (b["moduleDiffsCount"], "module(s) ran fewer tests or skipped more"), (b["newlySkippedCount"], "test(s) that passed before are skipped now")) if n]
    if b["executedDrop"]:
        gaps.append("executed tests dropped from %(before)d to %(now)d" % b["executedDrop"])
    if gaps:
        return "gap", "; ".join(gaps) + ".", True
    return "pass", "No regression: %d test(s) executed against %d in the baseline (%s)." % (b["fresh"]["counts"]["executed"], b["baseline"]["counts"]["executed"], b["baseline"]["source"]), True


def check_same(ctx, subject, paths, dev, dev_problem, base, evidence, caveats):
    """Check 3. `base` is baseline_state's answer for an uplift, else None."""
    uplift, dev_state, dev_detail = subject["track"] == "uplift", None, ""
    if dev:
        s = evidence["equivalence"] = summary_of(dev)
        problem = compare.verdict_of(dev)
        dev_state = "pass" if not problem else "fail"
        dev_detail = "%d of %d development case(s) executed: %d same%s, %d differ, %d missing; comparator self-check %s." % (
            s["executed"], s["cases"], s["same"], " (%d within a declared tolerance)" % s["withinTolerance"] if s["withinTolerance"] else "", s["differs"], s["missing"],
            {True: "passed", False: "FAILED", None: "not applicable"}[s["selfCheck"]])
        if problem and not (s["differs"] or s["missing"]):
            dev_detail = "Not proven: %s." % clean(problem, 200)
        if s["approved"]:
            dev_detail += " %d difference(s) a person approved are listed." % len(s["approved"])
        if recorded_matches(os.path.join(ctx["adir"], "EQUIVALENCE.json"), dev) is False:
            caveats.append("EQUIVALENCE.json does not match a fresh comparison of the cases: run compare.py again so the report shows the current result.")
        if paths["shared"]:
            caveats.append("The equivalence cases are shared by every module, so they are not attributed to this module alone.")
    elif dev_problem:
        caveats.append(dev_problem)
    if uplift:
        b_state, b_detail, comparable = base
        detail = " ".join(x for x in (b_detail, dev_detail) if x)
        if "fail" in (dev_state, b_state):
            return row("same", "fail", detail)
        if comparable:
            return row("same", b_state, detail)
        return row("same", "pass" if dev_state == "pass" else "gap", detail)
    if dev_state:
        return row("same", dev_state, dev_detail)
    if os.path.isfile(os.path.join(ctx["adir"], "EQUIVALENCE.json")):
        return row("same", "gap", "EQUIVALENCE.json exists, but the cases behind it (equivalence/cases.json) were not found, so it could not be judged again.")
    return row("same", "gap", "No equivalence cases were recorded: the new code was never compared with the legacy output.")


def input_labels(path):
    """{case id: input label} from the raw cases file. A case may carry "input": "F01" so that several output files of one
    run count as one input; a case without a label counts as its own input."""
    obj, _ = read_json(path)
    cases = obj.get("cases") if isinstance(obj, dict) and isinstance(obj.get("cases"), list) else []
    return {clean(c.get("id"), 80): clean(c.get("input"), 80) for c in cases[:100000] if isinstance(c, dict) and isinstance(c.get("input"), str) and c.get("input").strip()}


def check_fresh(ctx, paths, dev, legacy_ran, frs, fr_problem, evidence):
    """Check 4."""
    legacy = ctx["runs"]["legacy"]
    if ctx["runs"]["leftOut"]:
        evidence["leftOut"] = ctx["runs"]["leftOut"]
    if not legacy_ran:
        return row("fresh", "gap", "The legacy could not run here%s, so the proof is trace-based: no fresh-input comparison was possible and the verdict cannot be PROVEN." % (" (%s)" % legacy["why"] if legacy["why"] else ""))
    if frs is None:
        return row("fresh", "gap", "The fresh-input check was not run: no equivalence/fresh-cases.json%s." % (" (%s)" % fr_problem if fr_problem else ""))
    s = summary_of(frs)
    dev_hashes = {r["legacySha256"] for r in dev["cases"] if r["legacySha256"]} if dev else set()
    ran = ("same", "differs", "differs-approved")
    reused = {r["id"] for r in frs["cases"] if r["verdict"] in ran and r["legacySha256"] in dev_hashes}
    empty = {r["id"] for r in frs["cases"] if r["verdict"] in ran and r.get("empty")}
    labels = input_labels(paths["fresh"])
    counted = [r["id"] for r in frs["cases"] if r["verdict"] in ran and r["id"] not in reused and r["id"] not in empty]
    inputs = len({labels.get(c) or c for c in counted})
    s.update({"reused": sorted(reused)[:LIST_CAP], "comparisons": len(counted), "inputs": inputs, "needed": FRESH_MIN})
    evidence["fresh"] = s
    if ctx["runs"]["leftOut"]:
        s["leftOut"] = ctx["runs"]["leftOut"]
    if s["differs"] or s["missing"] or s["selfCheck"] is False:
        shown = s["differing"][:5]
        why = "; ".join("%s: %s" % (d["id"], d["reason"]) for d in shown) or "the comparator's self-check failed"
        more = " ... and %d more (see VERIFICATION.json)" % (s["differs"] + s["missing"] - len(shown)) if s["differs"] + s["missing"] > len(shown) else ""
        return row("fresh", "fail", "%d fresh comparison(s) differ and %d are missing (of %d): %s%s" % (s["differs"], s["missing"], s["cases"], why, more))
    if inputs < FRESH_MIN:
        return row("fresh", "gap", "Only %d new input(s) counted; at least %d are needed%s." % (inputs, FRESH_MIN, " (%d comparison(s) had the same legacy output as a development case, which is expected of status lines and does not count)" % len(reused) if reused else ""))
    extra = ([" (%d approved by a person)" % len(s["approved"])] if s["approved"] else []) + ([" (%d within a declared tolerance)" % s["withinTolerance"]] if s["withinTolerance"] else [])
    return row("fresh", "pass", "%d new input(s), %d comparison(s), ran on the legacy and the new code with no difference%s." % (inputs, len(counted), "".join(extra)))


def canaries_in(text):
    """Canary lines in a notes file: [(change, tests failed)]. Only lines that say Canary are looked at, each cut short."""
    found = []
    for line in [ln for ln in (text or "").split("\n") if "anary" in ln[:2000]][:500]:
        for m in CANARY.finditer(line[:600]):
            found.append((clean(m.group(1), 200), int(m.group(2).replace(",", ""))))
    return found


def canary_run(entry, workspace, clean_ids, clean_failed):
    """Failures a canary run's own result file or saved runner log shows beyond the clean run's: (new failures or None, where).
    With result files, a test that fails in both runs is not the canary's doing; with a log, only the count can be compared."""
    junit, logs = [p for p in (inside(workspace, j) for j in entry["junit"]) if p], [p for p in (inside(workspace, j) for j in entry["log"]) if p]
    if junit:
        fresh = baseline_diff.read_results(junit)
        if fresh["files"]:
            bad = {t for t, st in fresh["tests"].items() if st in ("FAIL", "ERROR")}
            return len(bad - clean_ids), [os.path.relpath(p, workspace).replace(os.sep, "/") for p in junit][:3]
    if logs:
        got = read_logs(logs)
        if got["files"]:
            return max(0, got["failed"] - clean_failed), [os.path.relpath(p, workspace).replace(os.sep, "/") for p in logs][:3]
    return None, []


def check_canary(subject, module, runs, evidence, workspace, others, clean_ids, clean_failed):
    """Check 5. A canary counts only when its own result file or saved runner log, parsed here, shows tests that fail because of the break
    (failures the clean run did not have). A line in the notes, or a count typed into test-runs.json, is a claim."""
    shown, claimed = [], []
    for c in runs["canaries"]:
        mine = c["module"].lower() in ("", module.lower()) or (subject["track"] == "uplift" and c["module"].lower() not in others)
        if not mine:
            continue
        failed, where = canary_run(c, workspace, clean_ids, clean_failed)
        (shown if failed is not None else claimed).append({"change": c["change"], "testsFailed": failed if failed is not None else c["testsFailed"], "shown": failed is not None, "where": where})
    for name in NOTE_NAMES:
        claimed += [{"change": c, "testsFailed": n, "shown": False, "where": []} for c, n in canaries_in(read_text(os.path.join(subject["path"], name)))]
    evidence["canary"] = (shown + claimed)[:10]
    silent = [c for c in shown if c["testsFailed"] == 0]
    if silent:
        return row("canary", "fail", "A deliberate break was run and no test failed because of it: %s (%s)." % (silent[0]["change"] or "no description", ", ".join(silent[0]["where"])))
    if shown:
        first = shown[0]
        return row("canary", "pass", "%d canary run(s) shown by a result file or log; the first (%s) made %d more test(s) fail than the clean run (%s).%s" % (
            len(shown), first["change"] or "no description", first["testsFailed"], ", ".join(first["where"]), " %d more are only claimed." % len(claimed) if claimed else ""))
    if claimed:
        return row("canary", "gap", "A canary is claimed (%s) but no result file or saved runner log from that run is recorded, so it was not shown." % (claimed[0]["change"] or "no description"))
    return row("canary", "gap", "No canary is recorded (a deliberate one-line break that makes tests fail), so the tests were never shown able to fail.")


def check_source(ctx):
    """Check 6."""
    src, name = ctx["source"], "legacy/" + ctx["system"]
    if src["state"] == "clean":
        return row("source", "pass", "%s is untouched: %s. Checked %s." % (name, src["detail"], src["method"]))
    if src["state"] == "changed":
        return row("source", "gap", "%s has changed since the analysis began: %s. Checked %s.%s" % (name, src["detail"], src["method"], " First: %s." % ", ".join(src["files"][:3]) if src["files"] else ""))
    return row("source", "gap", "%s: %s. Checked %s." % (name, src["detail"], src["method"]))


def not_proven(subject, ev, legacy_ran):
    """What even a PROVEN verdict would not tell you, specific to this module."""
    out = ["It does not prove behavior on inputs nobody tried: the equivalence cases and the fresh inputs are samples, not the whole input space."]
    if not legacy_ran:
        out.append("The legacy could not run here, so the comparison rests on recorded outputs and traces. It is only as good as that recording.")
    masks = (ev.get("equivalence") or {}).get("masks") or []
    if masks:
        out.append("Fields the comparison ignored could hide a difference there: %s." % "; ".join(m["why"] for m in masks[:5]))
    for where, key in (("development cases", "equivalence"), ("fresh inputs", "fresh")):
        for t in (ev.get(key) or {}).get("tolerances") or []:
            out.append("Numbers may differ in the %s within a declared tolerance (relative %g, absolute %g) in %d case(s): %s. That is a person's rule, not an exact match." % (
                where, t["rel"] or 0, t["abs"] or 0, t["cases"], t["why"]))
    if (ev.get("equivalence") or {}).get("approved") or (ev.get("fresh") or {}).get("approved") or (ev.get("baseline") or {}).get("approvedCount"):
        out.append("A difference a person approved is a decision, not evidence.")
    out.append("It does not cover speed, capacity, security, concurrency, or anything the tests and cases do not exercise.")
    if subject["track"] != "uplift":
        out.append("It traces only the rules that were extracted: behavior nobody wrote down as a rule has no rule to trace.")
    out.append("A test that names a rule shows the rule is mentioned, not that the test is a good one. The canary shows only that some test can fail.")
    out.append("It does not replace the review and sign-off of the people who own the system.")
    return out


def evaluate(subject, ctx):
    """-> the module record: verdict, reasons, the six checks and the evidence behind each."""
    ws, module, uplift = ctx["workspace"], subject["name"], subject["track"] == "uplift"
    suites = suites_for(ctx["runs"], subject, ctx["unit"], ctx["subjects"])
    evidence, caveats, person = {}, [], []
    per, xml_paths, oldest, clean_ids = [], [], None, set()
    for s in suites:
        ev, fresh = suite_evidence(s, ws)
        per.append(ev)
        caveats += ["%s: %s" % (ev["name"] or "a suite", n) for n in ev["notes"]]
        if ev["oldest"] is not None:
            oldest = ev["oldest"] if oldest is None else min(oldest, ev["oldest"])
        if fresh:
            xml_paths += [p for p in (inside(ws, j) for j in s["junit"]) if p]
            clean_ids |= {t for t, st in fresh["tests"].items() if st in ("FAIL", "ERROR")}
    g = {k: sum(e[k] for e in per) for k in ("executed", "failed", "skipped", "skippedNoReason")}
    g.update({"suites": per, "stale": oldest is not None and code_mtime(subject["path"]) > oldest + 2})       # any result file older than the code: not a clean run
    evidence["tests"] = dict({k: g[k] for k in ("executed", "failed", "skipped", "skippedNoReason", "stale")},
                             suites=[{k: e.get(k, "") for k in ("name", "command", "date", "note", "source", "files", "written", "executed", "failed", "skipped")} for e in per][:20])
    base = baseline_state(ctx, suites, xml_paths, evidence, caveats, person) if uplift else None
    paths = cases_paths(ctx["adir"], module, len(ctx["subjects"]))
    dev, dev_problem = judge(paths["cases"]) if paths["cases"] else (None, None)
    frs, fr_problem = judge(paths["fresh"]) if paths["fresh"] else (None, None)
    legacy_ran = ctx["runs"]["legacy"]["ran"]
    if uplift and evidence.get("baseline", {}).get("targetOnly"):
        legacy_ran = False
    if legacy_ran is None:
        legacy_ran = bool(frs and frs["totals"]["executed"])
    evidence["legacy"] = dict(ctx["runs"]["legacy"], ran=legacy_ran)
    checks = [check_tests(g, uplift, bool(base and base[2])), check_rules(ctx, subject, evidence, caveats), check_same(ctx, subject, paths, dev, dev_problem, base, evidence, caveats),
              check_fresh(ctx, paths, dev, legacy_ran, frs, fr_problem, evidence), check_canary(subject, module, ctx["runs"], evidence, ws, {x["name"].lower() for x in ctx["subjects"] if x["track"] != "uplift"}, clean_ids, g["failed"]), check_source(ctx)]
    states = [c["state"] for c in checks]
    label = dict(CHECKS)
    return {"name": module, "track": subject["track"], "path": subject["rel"], "verdict": "NOT PROVEN" if "fail" in states else "PARTLY PROVEN" if "gap" in states else "PROVEN",
            "reasons": ["%s: %s" % (label[c["id"]], c["detail"]) for c in checks if c["state"] in ("fail", "gap")],
            "passed": ["%s: %s" % (label[c["id"]], c["detail"]) for c in checks if c["state"] == "pass"],
            "checks": checks, "evidence": evidence, "caveats": caveats[:20], "needsPerson": person[:10], "brief": ctx["brief"](module, subject["track"]),
            "notProven": not_proven(subject, evidence, legacy_ran), "verifiedAt": ctx["now"]}


# ---------------------------------------------------------------- putting the pack together
def build(system, workspace, module=None, now=None):
    """-> the pack (a dict). Raises InputError when nothing is built to verify."""
    workspace = os.path.abspath(workspace)
    adir = os.path.join(workspace, "analysis", system)
    now = now or datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    everything = trace_rules.discover_modules(workspace, system)
    if not everything:
        raise InputError("nothing is built under modernized/ for %s: run transform, uplift or reimagine first" % system)
    unit = None
    if module and not any(m["name"].lower() == module.lower() for m in everything):
        # not a module: it may be a unit inside an uplifted working copy, which narrows that copy's suites
        if not any(m["track"] == "uplift" and os.path.isdir(os.path.join(m["path"], module)) and not os.path.islink(os.path.join(m["path"], module)) for m in everything):
            raise InputError("nothing is built under modernized/ for %s module %s (built: %s)" % (system, module, ", ".join(clean(m["name"], 40) for m in everything[:10])))
        unit = module
    found = everything
    runs = load_test_runs(adir)
    try:
        tr, tr_problem = trace_rules.trace(workspace, system), ""
    except OSError as err:
        tr, tr_problem = None, "%s, so no rule can be traced (run /code-modernization:modernize-extract-rules %s)." % (clean(str(err), 200), system)
    brief = read_text(os.path.join(adir, "MODERNIZATION_BRIEF.md"))
    ctx = {"workspace": workspace, "adir": adir, "system": system, "runs": runs, "subjects": everything, "unit": unit, "trace": tr, "trace_problem": tr_problem, "now": now,
           "source": source_check(workspace, system, adir), "brief": lambda mod, track: brief_items(brief, mod, track)}
    mods = [evaluate(s, ctx) for s in sorted(found, key=lambda s: s["name"].lower())]
    problems = [clean(p, 300) for p in runs["problems"]] + ([] if runs["present"] else ["equivalence/test-runs.json was not found, so no test run is recorded and no module can be proven."])
    return {"v": 1, "system": clean(system, 100), "generated": now, "asked": clean(module or "", 100), "rules": list(RULES_TEXT), "legacy": dict(ctx["source"], ran=runs["legacy"]["ran"]),
            "problems": problems, "modules": mods, "signoff": {"name": "", "role": "", "date": "", "decision": ""}}


def overall(pack):
    counts = {v: sum(1 for m in pack["modules"] if m["verdict"] == v) for v in VERDICTS}
    pack["overall"] = {"verdict": "NOT PROVEN" if counts["NOT PROVEN"] or not pack["modules"] else "PARTLY PROVEN" if counts["PARTLY PROVEN"] else "PROVEN", "counts": counts}
    return pack


# ---------------------------------------------------------------- VERIFICATION.md
def cell(text):
    return clean(text, 400).replace("|", "\\|")


def render_md(pack):
    o = pack["overall"]
    out = ["# Verification: %s" % pack["system"], "",
           "Written by `scripts/proof_pack.py` on %s. Each module's verdict is computed from the evidence files by the fixed rules at the end of this page. No model's opinion is part of it." % pack["generated"], "",
           "**Overall: %s** (%s)" % (o["verdict"], ", ".join("%d %s" % (o["counts"][v], v.lower()) for v in VERDICTS if o["counts"][v]) or "no module"), ""]
    out += ["- " + p for p in pack["problems"]]
    if pack.get("asked"):
        out += ["", "You asked about `%s`. Every built module is judged from its current evidence files on every run, so no verdict here depends on an earlier run." % cell(pack["asked"])]
    src = pack["legacy"]
    out += ["", "Legacy source: `%s`%s. Could it run here: %s. The source was checked %s." % (src["path"], " (a link to `%s`)" % src["target"] if src["target"] else "", {True: "yes", False: "no", None: "not stated"}[src.get("ran")], src["method"]), "",
            "| Module | Track | Verdict | Tests executed | Failed | P0 rules tested | Same behavior | Fresh inputs |", "|---|---|---|---|---|---|---|---|"]
    for m in pack["modules"]:
        ev, st = m["evidence"], {c["id"]: c["state"] for c in m["checks"]}
        p0 = ev.get("rules", {}).get("p0", [])
        tested = "%d of %d" % (sum(1 for r in p0 if r["status"] == "tested"), len(p0)) if "rules" in ev else "not applicable"
        out.append("| %s | %s | **%s** | %d | %d | %s | %s | %s |" % (cell(m["name"]), m["track"], m["verdict"], ev["tests"]["executed"], ev["tests"]["failed"], tested, WORDS[st["same"]], WORDS[st["fresh"]]))
    for m in pack["modules"]:
        ev, t, br = m["evidence"], m["evidence"]["tests"], m["brief"]
        out += ["", "## %s: %s" % (cell(m["name"]), m["verdict"]), "", "Track: %s. Folder: `%s`. Checked %s." % (m["track"], cell(m["path"]), m["verifiedAt"]), ""]
        if m["reasons"]:
            out += ["**What is missing or wrong**", ""] + ["- " + cell(r) for r in m["reasons"]] + [""]
        if m["passed"]:
            out += ["**What passed**", ""] + ["- " + cell(r) for r in m["passed"]] + [""]
        out += ["| Check | Result | Detail |", "|---|---|---|"]
        out += ["| %s | %s | %s |" % (c["label"], WORDS[c["state"]], cell(c["detail"])) for c in m["checks"]]
        out += ["", "tests executed: %d, failed %d, skipped %d" % (t["executed"], t["failed"], t["skipped"]), ""]
        out += ["- %s: `%s` (from %s): %d executed, %d failed, %d skipped%s%s" % (cell(s["name"] or "suite"), cell(s["command"]), s["source"], s["executed"], s["failed"], s["skipped"],
                                                                                   ", %d result files written %s" % (s["files"], s["written"]) if s["files"] else "",
                                                                                   ". Note: " + cell(s["note"]) if s.get("note") else "") for s in t["suites"]]
        if ev.get("rules", {}).get("p0"):
            out += ["", "### P0 business rules", "", "| Rule | Name | Confidence | Result | Tests | Code | A test that names it |", "|---|---|---|---|---|---|---|"]
            out += ["| %s | %s | %s | %s | %d | %d | %s |" % (r["id"], cell(r["name"]), r["confidence"] or "?", r["status"], r["tests"], r["main"], "`%s`" % cell(r["where"]) if r["where"] and r["tests"] else "") for r in ev["rules"]["p0"]]
        if "equivalence" in ev:
            e = ev["equivalence"]
            out += ["", "### Development cases, judged again", "", "%d of %d executed: %d same%s, %d differ, %d missing." % (
                e["executed"], e["cases"], e["same"], " (%d within a declared tolerance)" % e["withinTolerance"] if e["withinTolerance"] else "", e["differs"], e["missing"])]
            out += ["- Declared tolerance (relative %g, absolute %g), %d case(s): %s" % (t["rel"] or 0, t["abs"] or 0, t["cases"], cell(t["why"])) for t in e["tolerances"]]
            out += ["- Approved difference %s: %s" % (cell(a["id"]), cell(a["why"])) for a in e["approved"]] + ["- Ignored by the comparison: %s (%d case(s))" % (cell(x["why"]), x["cases"]) for x in e["masks"]]
            out += ["- %s: %s" % (cell(d["id"]), cell(d["reason"])) for d in e["differing"]]
        if "baseline" in ev:
            b = ev["baseline"]
            out += ["", "### Baseline comparison", "", "%d regression(s), %d new failure(s), %d fixed, %d missing, %d renamed." % (b["regressionsCount"], b["newFailuresCount"], b["fixedCount"], b["missingCount"], b["renamed"])]
            out += ["- Regression: %s (%s, now %s)" % (cell(x["id"]), x["before"], x["now"]) for x in b["regressions"][:10]] + ["- New failure: " + cell(x) for x in b["newFailures"][:10]]
        if ev.get("baseline", {}).get("approvedCount"):
            out += ["- Difference a person approved in BASELINE.md: %s (%s)" % (cell(x["id"]), cell(x["reason"] or "no reason given")) for x in ev["baseline"]["approved"][:10]]
        if ev.get("leftOut"):
            out += ["", "Inputs left out of the fresh check: " + "; ".join(cell(x) for x in ev["leftOut"])]
        if "fresh" in ev:
            f = ev["fresh"]
            out += ["", "### Fresh inputs", "", "%d new input(s) counted from %d comparison(s) executed: %d same%s, %d differ, %d missing." % (
                f["inputs"], f["executed"], f["same"], " (%d within a declared tolerance)" % f["withinTolerance"] if f["withinTolerance"] else "", f["differs"], f["missing"])]
            out += ["- Declared tolerance (relative %g, absolute %g), %d case(s): %s" % (t["rel"] or 0, t["abs"] or 0, t["cases"], cell(t["why"])) for t in f["tolerances"]]
            out += ["- Not counted, because the legacy output equals a development output (status lines repeat by nature): " + ", ".join(cell(x) for x in f["reused"][:20])] if f["reused"] else []
        out += (["", "### Caveats", ""] + ["- " + cell(c) for c in m["caveats"]]) if m["caveats"] else []
        out += ["", "### Waiting for a person", "", "Claude never ticks these. A person decides them.", ""]
        out += ["- [ ] %s [%s]" % (cell(i["text"]), i["where"]) for i in br["items"]] + ["- [ ] " + cell(n) for n in m["needsPerson"]]
        if not br["items"] and not m["needsPerson"]:
            out.append("- The brief lists no unticked criterion for this module." if br["found"] else "- No MODERNIZATION_BRIEF.md was found, so no criterion could be listed.")
        if br["count"] > len(br["items"]):
            out.append("- ... and %d more in the brief." % (br["count"] - len(br["items"])))
        out += ["", "### What this does not prove", ""] + ["- " + cell(n) for n in m["notProven"]]
    s = pack["signoff"]
    out += ["", "## Sign-off", "", "A person fills this in. Claude leaves it blank.", "", "| | |", "|---|---|", "| Name | %s |" % (s["name"] or "________________"), "| Role | %s |" % (s["role"] or "________________"),
            "| Date | %s |" % (s["date"] or "__________"), "| Decision | %s |" % (s["decision"] or "accept / accept with conditions / reject"), "", "## How each verdict is computed", ""]
    return "\n".join(out + [pack["rules"][0], ""] + pack["rules"][1:]) + "\n"


def write_outputs(pack, adir):
    for name, text in (("VERIFICATION.json", json.dumps(pack, indent=2, ensure_ascii=True) + "\n"), ("VERIFICATION.md", render_md(pack))):
        try:
            compare.write_atomic(os.path.join(adir, name), text)
        except compare.InputError as err:
            raise InputError(str(err))


def main(argv=None):
    ap = argparse.ArgumentParser(description="Compute a verdict per built module from the evidence files and write VERIFICATION.md and VERIFICATION.json.")
    ap.add_argument("system", help="the system's folder name under analysis/")
    ap.add_argument("module", nargs="?", help="the module you re-tested (or a unit of an uplifted copy); every built module is judged from its current evidence either way")
    ap.add_argument("--workspace", default=".", help="the project root holding analysis/ and modernized/ (default: current folder)")
    args = ap.parse_args(argv)
    for name in (args.system, args.module or "x"):
        if not name or name in (".", "..") or re.search(r"[\\/\x00]", name):
            print("proof_pack.py: the system and module must be folder names, not paths", file=sys.stderr)
            return 2
    adir = os.path.join(os.path.abspath(args.workspace), "analysis", args.system)
    try:
        pack = overall(build(args.system, args.workspace, args.module))
        os.makedirs(adir, exist_ok=True)
        write_outputs(pack, adir)
    except InputError as err:
        print("proof_pack.py: %s" % err, file=sys.stderr)
        return 2
    print("%s: %s" % (pack["system"], pack["overall"]["verdict"]))
    for m in pack["modules"]:
        print("  %s (%s): %s, tests executed: %d, failed %d" % (clean(m["name"], 60), m["track"], m["verdict"], m["evidence"]["tests"]["executed"], m["evidence"]["tests"]["failed"]))
        for r in m["reasons"]:
            print("    - " + clean(r, 300))
    print("wrote analysis/%s/VERIFICATION.md and VERIFICATION.json" % args.system)
    return 0 if pack["overall"]["verdict"] == "PROVEN" else 1


if __name__ == "__main__":
    sys.exit(main())
