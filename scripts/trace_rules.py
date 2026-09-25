#!/usr/bin/env python3
"""Trace every business rule to the code and the tests that name it.

    python3 trace_rules.py <system> [--workspace DIR] [--json] [--all]

Reads analysis/<system>/BUSINESS_RULES.md (rule cards: "### RULE-NNN: name" with **Priority:**,
**Confidence:** and **Source:** lines), then scans the built code under modernized/<system>,
modernized/<system>-uplifted and modernized/<system>-reimagined (never build output: target/,
build/, dist/, node_modules/, bin/, obj/, __pycache__/, or any folder starting with a dot) for
mentions of each rule id, and sorts every file into "test" or "main" code. One row per rule.

Evidence, strongest first:
  tested        a test file names the rule
  code only     only main code names it
  claimed only  only the mapping table in TRANSFORMATION_NOTES.md or UPLIFT_NOTES.md names it, on a
                row that also names a file that exists in the module
  none          nothing names it

A mention is RULE-017 (any case, or RULE_017), rule017 or Rule017 inside an identifier such as
rule017_emptyInput or testRule017, and the shorthand RULE-002/003 and RULE-001, -018. Nothing is
guessed from words: a rule that no file names by id is not "tested", however well its behavior may
be covered. A mention shows that a test names the rule, not that the test is good.

A test is a file under a folder called test, tests, __tests__, spec or specs, or named like
FooTest.java, FooTests.cs, TestFoo.java, test_foo.py, foo_test.go, foo.spec.ts or foo.test.js.
Documentation files (.md, .txt, .rst, .adoc) are never code. Symbolic links are never followed.
Everything read is untrusted text: it is never executed and only shortened, never trusted.

Exit 0 when every P0 rule has a test that names it, 1 when some do not, 2 when the rules file
cannot be read. Standard library only.
"""
import argparse
import collections
import json
import os
import re
import sys

SKIP_DIRS = {"target", "build", "dist", "node_modules", "bin", "obj", "__pycache__", "venv"}
DOC_EXT = {".md", ".markdown", ".rst", ".txt", ".adoc"}
TEST_DIRS = {"test", "tests", "__tests__", "spec", "specs"}
TEST_NAME = re.compile(r"^test_|_tests?\.[^.]+$|\.(?:spec|test)\.[^.]+$|(?:Test|Tests|TestCase|IT)\.[^.]+$|^Test[A-Z0-9_]")
NOTES_NAMES = ("TRANSFORMATION_NOTES.md", "UPLIFT_NOTES.md")
TRACKS = (("rewrite", ""), ("uplift", "-uplifted"), ("reimagine", "-reimagined"))
FILE_CAP, RULES_CAP, NOTES_CAP, LINE_CAP, MAX_FILES, SAMPLES = 2 << 20, 8 << 20, 1 << 20, 4000, 200000, 3
MENTION = [re.compile(r"(?<![A-Za-z0-9])rule[-_](\d{1,6})(?!\d)", re.I),
           re.compile(r"(?<![A-Za-z0-9])rule(\d{3,6})(?!\d)", re.I),
           re.compile(r"(?<=[a-z])Rule[-_]?(\d{3,6})(?!\d)")]
MORE = re.compile(r"(?:/|,[ \t]*-)(\d{2,6})(?!\d)")
NOT_A_CLAIM = re.compile(r"(?i)not migrated|not implemented|not ported|removed|retired|dead code|dropped|out of scope")
CARD = re.compile(r"#{2,5}[ \t]+[*`\[]*RULE[-_](\d{1,6})(?![A-Za-z0-9])", re.I)
FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
PATH = re.compile(r"[A-Za-z0-9_@][A-Za-z0-9_@./+-]{0,199}\.[A-Za-z][A-Za-z0-9]{0,7}(?![A-Za-z0-9_])")


def clean(value, limit=200):
    text = " ".join(re.sub(r"[\x00-\x1f\x7f-\x9f\u2028\u2029]", " ", str(value if value is not None else "")).split())
    return text if len(text) <= limit else text[:limit - 1] + "\u2026"


def read_text(path, cap):
    """Text of a regular, non-binary file (first `cap` bytes), or None."""
    try:
        with open(path, "rb") as fh:
            raw = fh.read(cap)
    except OSError:
        return None
    return None if b"\x00" in raw[:4096] else raw.decode("utf-8", "replace")


def find_ids(text):
    """[(rule number, offset)] for every id named in text, shorthand included."""
    found = []
    for rx in MENTION:
        for m in rx.finditer(text):
            found.append((int(m.group(1)), m.start()))
            pos = m.end()
            more = MORE.match(text, pos)
            while more:
                found.append((int(more.group(1)), m.start()))
                pos = more.end()
                more = MORE.match(text, pos)
    return found


def field(lines, name):
    """The value of a "**Name:** value" line, or ''. Linear in the line length whatever the line holds."""
    for line in lines:
        s = line[:LINE_CAP].lstrip(" \t>*-")
        if s[:len(name)].lower() == name.lower():
            rest = s[len(name):].lstrip("*").lstrip(" \t")
            if rest.startswith(":"):
                return rest[1:].lstrip(" \t*").strip()
    return ""


def parse_rules(text):
    """-> ([rule dicts in file order], [notes]). A duplicate id keeps its first card."""
    rules, notes, seen, card, fence, rows = [], [], set(), None, "", {}
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    for line in lines:
        if line.lstrip().startswith("|"):
            cells = [re.sub(r"[*`]", "", c).strip() for c in line[:LINE_CAP].strip().strip("|").split("|")]
            ids = [int(m.group(1)) for c in cells for m in [re.fullmatch(r"RULE[-_](\d{1,6})", c, re.I)] if m]
            if ids:
                rows.setdefault(ids[0], {"p": next((c for c in cells if re.fullmatch(r"P\d", c)), ""),
                                         "c": next((c for c in cells if re.match(r"(?i)(high|medium|low)\b", c)), "")})
    for line in lines:
        f = FENCE.match(line)
        if fence:
            fence = "" if f and f.group(1)[0] == fence[0] and len(f.group(1)) >= len(fence) else fence
            if card is not None:
                card["body"].append(line)
            continue
        if f:
            fence = f.group(1)
        m = None if f else CARD.match(line[:LINE_CAP])
        if not f and re.match(r"#{1,6}\s", line):
            card = None
        if m:
            n = int(m.group(1))
            if n in seen:
                notes.append("RULE-%03d has more than one card; the first was used." % n)
                continue
            seen.add(n)
            name = line[m.end():LINE_CAP].lstrip("*`] \t:\u00b7\u2013\u2014-").rstrip("# \t")
            card = {"n": n, "id": "RULE-%03d" % n, "name": clean(name, 160), "body": []}
            rules.append(card)
        elif card is not None:
            card["body"].append(line)
    for r in rules:
        body = r.pop("body")
        prio = re.search(r"\bP\d\b", field(body, "Priority"))
        conf = re.search(r"(?i)\b(high|medium|low)\b", field(body, "Confidence"))
        row = rows.get(r["n"], {})
        source = field(body, "Source")
        first = PATH.search(source)
        r.update({"priority": prio.group(0) if prio else row.get("p", ""),
                  "confidence": conf.group(1).capitalize() if conf else row.get("c", "").capitalize()[:10],
                  "source": clean(source, 160), "sourceFile": os.path.basename(first.group(0)) if first else ""})
    return rules, notes


def file_kind(rel):
    parts = rel.split("/")
    name = parts[-1]
    if os.path.splitext(name)[1].lower() in DOC_EXT:
        return "doc"
    if any(p.lower() in TEST_DIRS for p in parts[:-1]) or TEST_NAME.search(name):
        return "test"
    return "main"


def is_real_dir(path):
    return os.path.isdir(path) and not os.path.islink(path)


def discover_modules(workspace, system):
    """[{name, track, path, rel}] for every built module under modernized/."""
    out = []
    for track, suffix in TRACKS:
        root = os.path.join(workspace, "modernized", system + suffix)
        if not is_real_dir(root):
            continue
        rel = "modernized/" + system + suffix
        if track == "uplift":
            out.append({"name": system + suffix, "track": track, "path": root, "rel": rel})
            continue
        try:
            subs = sorted(d for d in os.listdir(root) if not d.startswith(".") and d not in SKIP_DIRS and is_real_dir(os.path.join(root, d)))
        except OSError:
            subs = []
        for d in subs:
            out.append({"name": d, "track": track, "path": os.path.join(root, d), "rel": rel + "/" + d})
        if not subs:
            out.append({"name": system + suffix, "track": track, "path": root, "rel": rel})
    return out


def walk_module(path, budget):
    """([(relative posix path, absolute path)] of regular files, links skipped, cut short)."""
    files, skipped = [], 0
    for base, dirs, names in os.walk(path):
        keep = []
        for d in sorted(dirs):
            if d.startswith(".") or d in SKIP_DIRS:
                continue
            if os.path.islink(os.path.join(base, d)):
                skipped += 1
                continue
            keep.append(d)
        dirs[:] = keep
        for n in sorted(names):
            full = os.path.join(base, n)
            if os.path.islink(full):
                skipped += 1
            elif not n.startswith(".") and os.path.isfile(full):
                if len(files) >= budget:
                    return files, skipped, True
                files.append((os.path.relpath(full, path).replace(os.sep, "/"), full))
    return files, skipped, False


def claims_of(notes, names):
    """(rule numbers claimed, rule rows naming no existing file, basenames of every file the notes name).
    A row claims a rule only when it names the rule AND a file that exists in the module."""
    claimed, unresolved, named, head = set(), 0, set(), ""
    for line in notes.split("\n"):
        line = line[:LINE_CAP]
        tokens = PATH.findall(line)
        named.update(os.path.basename(t) for t in tokens)
        if line.startswith("#"):
            head = line.lstrip("#").strip()
        if not line.lstrip().startswith("|") or NOT_A_CLAIM.search(head):      # a table under "Not migrated" claims nothing
            continue
        ids = {n for n, _ in find_ids(line)}
        if not ids:
            continue
        if any(os.path.basename(t) in names and any(p == t or p.endswith("/" + t) for p in names[os.path.basename(t)]) for t in tokens):
            claimed |= ids
        else:
            unresolved += 1
    return claimed, unresolved, named


def status_of(main, tests, claimed):
    return "tested" if tests else "code only" if main else "claimed only" if claimed else "none"


def blank():
    return {"main": 0, "tests": 0, "claimed": False, "named": False}


def trace(workspace, system):
    """-> the trace. Raises OSError when BUSINESS_RULES.md cannot be read."""
    rules_path = os.path.join(workspace, "analysis", system, "BUSINESS_RULES.md")
    if os.path.islink(rules_path):
        raise OSError("analysis/%s/BUSINESS_RULES.md is a symbolic link" % system)
    text = read_text(rules_path, RULES_CAP)
    if text is None:
        raise OSError("analysis/%s/BUSINESS_RULES.md is missing or is not text" % system)
    rules, notes = parse_rules(text)
    by_n = {r["n"]: r for r in rules}
    per = {r["n"]: {} for r in rules}
    samples = {r["n"]: {"main": [], "tests": []} for r in rules}
    modules, budget = [], MAX_FILES
    scan = {"files": 0, "textFiles": 0, "linksSkipped": 0, "cut": False}
    for mod in discover_modules(workspace, system):
        files, skipped, cut = walk_module(mod["path"], budget)
        budget -= len(files)
        names = collections.defaultdict(list)
        for rel, _ in files:
            names[os.path.basename(rel)].append(rel)
        notes_name = next((n for n in NOTES_NAMES if n in names[n]), "")
        claimed, unresolved, named = set(), 0, set()
        if notes_name:
            ntext = read_text(os.path.join(mod["path"], notes_name), NOTES_CAP)
            if ntext is not None:
                claimed, unresolved, named = claims_of(ntext, names)
        test_files = 0
        for rel, full in files:
            kind = file_kind(rel)
            if kind == "doc":
                continue
            key = "tests" if kind == "test" else "main"
            test_files += kind == "test"
            body = read_text(full, FILE_CAP)
            scan["textFiles"] += body is not None
            hits = [(n, None) for n, _ in find_ids(os.path.basename(rel))] + [(n, at) for n, at in find_ids(body or "")]
            for n, at in hits:
                if n not in by_n:
                    continue
                per[n].setdefault(mod["rel"], blank())[key] += 1
                place = "%s/%s" % (mod["rel"], rel)
                if len(samples[n][key]) < SAMPLES and not any(s.rsplit(":", 1)[0] == place for s in samples[n][key]):
                    samples[n][key].append("%s:%d" % (place, 0 if at is None else body.count("\n", 0, at) + 1))
        for n in claimed & set(by_n):
            per[n].setdefault(mod["rel"], blank())["claimed"] = True
        for r in rules:
            if r["sourceFile"] and r["sourceFile"] in named:
                per[r["n"]].setdefault(mod["rel"], blank())["named"] = True
        scan["files"] += len(files)
        scan["linksSkipped"] += skipped
        scan["cut"] = scan["cut"] or cut
        modules.append({"name": mod["name"], "track": mod["track"], "path": mod["rel"], "files": len(files), "testFiles": test_files,
                        "notes": notes_name, "claimRowsUnresolved": unresolved})
    out = []
    for r in rules:
        slots = per[r["n"]]
        main, tests_n = sum(s["main"] for s in slots.values()), sum(s["tests"] for s in slots.values())
        claim = any(s["claimed"] for s in slots.values())
        out.append({"id": r["id"], "name": r["name"], "priority": r["priority"], "confidence": r["confidence"], "source": r["source"],
                    "main": main, "tests": tests_n, "claimed": claim, "status": status_of(main, tests_n, claim),
                    "perModule": slots, "samples": samples[r["n"]]})
    if scan["cut"]:
        notes.append("More than %d files were found, so the scan stopped early." % MAX_FILES)
    if scan["linksSkipped"]:
        notes.append("%d symbolic link(s) were not followed." % scan["linksSkipped"])
    if not modules:
        notes.append("No built code was found under modernized/%s, %s-uplifted or %s-reimagined." % (system, system, system))
    return {"system": clean(system, 100), "rulesFile": "analysis/%s/BUSINESS_RULES.md" % system, "modules": modules, "rules": out,
            "totals": totals(out), "p0NoTests": [r["id"] for r in out if r["priority"] == "P0" and r["status"] != "tested"],
            "scan": scan, "notes": notes}


def totals(rows):
    """Per priority: rules, and how many are tested / code only / claimed only / none."""
    out = {}
    for r in rows:
        t = out.setdefault(r["priority"] or "unrated", {"rules": 0, "tested": 0, "code only": 0, "claimed only": 0, "none": 0})
        t["rules"] += 1
        t[r["status"]] += 1
    return dict(sorted(out.items()))


def module_view(result, rel):
    """The rules one module answers for, each with the module's own status. A rewrite answers for the rules its code,
    tests or notes name, or whose legacy file its notes name; an uplift keeps the whole code, so it answers for all.
    When nothing ties any rule to the module, every rule counts (`tied` is then False): an empty list must never pass."""
    mod = next((m for m in result["modules"] if m["path"] == rel), None)
    rows, tied = [], True
    for r in result["rules"]:
        slot = r["perModule"].get(rel) or blank()
        if mod and (mod["track"] == "uplift" or slot["main"] or slot["tests"] or slot["claimed"] or slot["named"]):
            rows.append(dict(r, main=slot["main"], tests=slot["tests"], claimed=slot["claimed"], status=status_of(slot["main"], slot["tests"], slot["claimed"])))
    if mod and not rows and result["rules"]:
        tied = False
        for r in result["rules"]:
            slot = r["perModule"].get(rel) or blank()
            rows.append(dict(r, main=slot["main"], tests=slot["tests"], claimed=slot["claimed"], status=status_of(slot["main"], slot["tests"], slot["claimed"])))
    return {"rows": rows, "totals": totals(rows), "outOfScope": len(result["rules"]) - len(rows), "tied": tied,
            "p0NoTests": [r["id"] for r in rows if r["priority"] == "P0" and r["status"] != "tested"]}


def render(result, everything=False, view=None, module=None):
    """The matrix as text. With `view` (from module_view) only the rules that module answers for are listed."""
    rows = view["rows"] if view else result["rules"]
    tot = view["totals"] if view else result["totals"]
    missing = view["p0NoTests"] if view else result["p0NoTests"]
    scanned = ", ".join("%s (%d files, %d test)" % (clean(m["name"], 60), m["files"], m["testFiles"]) for m in result["modules"]
                        if not module or m["name"] == module) or "nothing built yet"
    head = "Rule trace for %s%s: %d rule(s) in %s" % (result["system"], ", module " + clean(module, 60) if module else "", len(result["rules"]), result["rulesFile"])
    lines = [head, "Scanned: " + scanned]
    if view:
        lines.append("Counted for this module: %d rule(s)%s" % (len(rows), "" if view["tied"] else " (nothing ties a rule to it by name, so every rule counts)"))
    lines.append("")
    for p, c in tot.items():
        lines.append("%-7s %3d rules: %d tested, %d code only, %d claimed only, %d none" % (p, c["rules"], c["tested"], c["code only"], c["claimed only"], c["none"]))
    lines += ["", "%-9s %-4s %-7s %5s %5s  %s" % ("Rule", "Pri", "Conf", "Code", "Tests", "Status")]
    shown = [r for r in rows if everything or r["priority"] == "P0"] + ([] if everything else [r for r in rows if r["priority"] != "P0"][:40])
    for r in shown:
        lines.append("%-9s %-4s %-7s %5d %5d  %s  %s" % (r["id"], r["priority"] or "-", r["confidence"] or "-", r["main"], r["tests"], r["status"], clean(r["name"], 60)))
    if len(shown) < len(rows):
        lines.append("... %d more rule(s) not listed (use --all)" % (len(rows) - len(shown)))
    lines += ["", "P0 rules with no test that names them: " + (", ".join(missing) if missing else "none")]
    lines += ["Note: " + n for n in result["notes"]]
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Trace business rules to the code and tests that name them.")
    ap.add_argument("system", help="the system's folder name under analysis/")
    ap.add_argument("--workspace", default=".", help="the project root holding analysis/ and modernized/ (default: current folder)")
    ap.add_argument("--json", action="store_true", help="print the full trace as JSON")
    ap.add_argument("--all", action="store_true", help="list every rule, not just P0 and the first 40 others")
    ap.add_argument("--module", metavar="NAME", help="only the rules this built module answers for (a folder under modernized/<system>/)")
    args = ap.parse_args(argv)
    if not args.system or args.system in (".", "..") or re.search(r"[\\/\x00]", args.system):
        print("trace_rules.py: the system must be a folder name under analysis/, not a path", file=sys.stderr)
        return 2
    try:
        result = trace(args.workspace, args.system)
    except OSError as err:
        print("trace_rules.py: %s" % err, file=sys.stderr)
        return 2
    view, mod = None, None
    if args.module:
        mod = next((m for m in result["modules"] if m["name"].lower() == args.module.lower()), None)
        if mod is None:
            print("trace_rules.py: no built module called %s (found: %s)" % (clean(args.module, 60), ", ".join(clean(m["name"], 40) for m in result["modules"]) or "none"), file=sys.stderr)
            return 2
        view = module_view(result, mod["path"])
    if args.json:
        print(json.dumps(dict(result, moduleView=view) if view else result, indent=1, ensure_ascii=True))
    else:
        print(render(result, args.all, view, mod["name"] if mod else None))
    return 1 if (view["p0NoTests"] if view else result["p0NoTests"]) else 0


if __name__ == "__main__":
    sys.exit(main())
