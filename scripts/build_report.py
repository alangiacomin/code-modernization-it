#!/usr/bin/env python3
"""Build one self-contained HTML report from a system's modernization artifacts.

    python3 build_report.py <system> [--workspace DIR] [--out FILE]

Reads whatever exists under <workspace>/analysis/<system>/ and <workspace>/modernized/ (every file is
optional; a missing or malformed one is reported in the page, never an error) and writes
<workspace>/analysis/<system>/REPORT.html by default. Standard library only. Exit 0; 1 when nothing
at all was found; 2 for a system name that is not a folder name.

The artifacts come from untrusted code, so every byte is treated as hostile: text travels only as
escaped JSON inside <script type="application/json"> blocks, the page builds its DOM with
textContent, a Content-Security-Policy pins the only scripts that may run (by hash) and blocks every
external request, and files named *.local.*, SECRETS* or reached through a symlink are never read.
"""
import argparse
import base64
import collections
import datetime
import hashlib
import json
import os
import re
import stat
import sys
import tempfile
from urllib.parse import quote

HERE = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.join(os.path.dirname(HERE), "assets")
FILE_CAP, TOTAL_CAP, LINE_CAP, MAX_CASES, MAX_NOTES = 3 << 20, 6 << 20, 20000, 2000, 100
NOTE_NAMES = ("TRANSFORMATION_NOTES.md", "UPLIFT_NOTES.md", "README.md")
STEPS = [("preflight", "Preflight"), ("assess", "Assess"), ("map", "Map"), ("rules", "Rules"),
         ("brief", "Brief"), ("build", "Build"), ("harden", "Harden")]
TITLES = [("overview", "Overview"), ("assessment", "Assessment"), ("diagrams", "Diagrams"),
          ("rules", "Business rules"), ("brief", "Brief"), ("security", "Security"),
          ("delta", "Delta catalog & baseline"), ("spec", "Spec & architecture"),
          ("build", "Build notes"), ("equivalence", "Equivalence")]
DOCS = [("overview", ["PREFLIGHT.md"]), ("assessment", ["ASSESSMENT.md"]),
        ("rules", ["BUSINESS_RULES.md", "RULE_REVIEWS.md", "DATA_OBJECTS.md"]), ("brief", ["MODERNIZATION_BRIEF.md"]),
        ("security", ["SECURITY_FINDINGS.md"]), ("delta", ["DELTA_CATALOG.md", "BASELINE.md", "PLAYBOOK.md"]),
        ("spec", ["AI_NATIVE_SPEC.md", "REIMAGINED_ARCHITECTURE.md"])]
MERMAID_FENCE = re.compile(r"(?m)^ {0,3}(?:`{3,}|~{3,})[ \t]*mermaid\b")
ID = r"[A-Z][A-Z0-9]*(?:-[A-Z][A-Z0-9]*)*-\d+[a-z]?"
CARD = re.compile(r"^(#{3,4})[ \t]+[*`]*(" + ID + r")[*`]*(?:[ \t]*[·:\-–—][ \t]*(.*?))?[ \t]*#*[ \t]*$")
FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
CITE = re.compile(r"[A-Za-z0-9_][\w./+-]*\.[A-Za-z][A-Za-z0-9]{0,7}:\d+(?:-\d+)?(?:,\s*\d+(?:-\d+)?)*")
DAY = "%Y-%m-%d"


def num(n):
    return "{:,}".format(n)


def utc_day(ts):
    return datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).strftime(DAY)


# ---------------------------------------------------------------- reading files safely
class Source:
    """Everything read from the workspace goes through here: caps, notes, and refusals."""

    def __init__(self, workspace, system):
        self.root, self.system, self.used = os.path.realpath(workspace), system, 0
        self.adir, self.mdir = os.path.join(workspace, "analysis", system), os.path.join(workspace, "modernized")
        self.notes, self.found = [], []

    def read(self, path, label):
        """Cleaned text of a regular file inside the workspace; None when absent or refused."""
        name = os.path.basename(path).lower()
        if ".local." in name or name.startswith("secrets"):
            return None
        try:
            st = os.lstat(path)
        except OSError:
            return None
        if not stat.S_ISREG(st.st_mode) or os.path.commonpath([self.root, os.path.realpath(path)]) != self.root:
            self.notes.append("%s is a link or not a regular file inside the workspace, so it was not read." % label)
            return None
        self.found.append((label, st.st_size, utc_day(st.st_mtime)))
        try:
            with open(path, "rb") as fh:
                raw = fh.read(FILE_CAP + 1)
        except OSError as err:
            self.notes.append("%s could not be read (%s)." % (label, err.__class__.__name__))
            return ""
        text = raw[:FILE_CAP].decode("utf-8", "replace").lstrip("\N{ZERO WIDTH NO-BREAK SPACE}").replace("\r\n", "\n").replace("\r", "\n")
        lines, shortened = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "\N{REPLACEMENT CHARACTER}", text).split("\n"), 0
        for i, line in enumerate(lines):
            if len(line) > LINE_CAP:
                lines[i] = "%s ... [%s more characters not shown]" % (line[:LINE_CAP], num(len(line) - LINE_CAP))
                shortened += 1
        text = "\n".join(lines)
        if shortened:
            self.notes.append("%s: %d line(s) longer than %s characters were shortened." % (label, shortened, num(LINE_CAP)))
        room = TOTAL_CAP - self.used
        if len(raw) > FILE_CAP or len(text.encode("utf-8")) > room:
            text = text.encode("utf-8")[:max(0, min(FILE_CAP, room))].decode("utf-8", "ignore")
            text = text[:text.rfind("\n")] if "\n" in text else ""
            self.notes.append("%s: %s (report size limit; the file is %s KB)." % (
                label, "only the first %s KB is included" % num(len(text.encode("utf-8")) >> 10) if text else "left out",
                num(max(1, st.st_size >> 10))))
        self.used += len(text.encode("utf-8"))
        return text

    def json(self, path, label):
        """-> (parsed value or None, whether the file exists)."""
        text = self.read(path, label)
        if text is None:
            return None, False
        try:
            return json.loads(text), True
        except ValueError as err:
            self.notes.append("%s could not be parsed as JSON (%s)." % (label, str(err)[:80]))
            return None, True


# ---------------------------------------------------------------- what the markdown says
def cells(line):
    s = line.strip()
    s = s[1:] if s.startswith("|") else s
    s = s[:-1] if s.endswith("|") and not s.endswith("\\|") else s
    return [re.sub(r"[*`]", "", c).strip() for c in re.split(r"(?<!\\)\|", s)]


def tables(text):
    """(nearest heading, header cells, rows) for every pipe table in a markdown text."""
    lines, head = text.split("\n"), ""
    for i, line in enumerate(lines):
        m = re.match(r"#{1,6}\s+(.*)", line)
        head = m.group(1) if m else head
        if "|" in line and i + 1 < len(lines) and "|" in lines[i + 1] and re.fullmatch(r"\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)*\|?\s*", lines[i + 1]):
            rows, j = [], i + 2
            while j < len(lines) and "|" in lines[j] and lines[j].strip():
                rows.append(cells(lines[j]))
                j += 1
            yield head, cells(line), rows


def field(body, name):
    m = re.search(r"(?im)^[ \t>*-]*\**" + name + r"\**[ \t]*:[ \t]*\**[ \t]*(.+?)[ \t]*$", body)
    return m.group(1) if m else ""


def parse_rules(text):
    """Split a rules file into markdown chunks and rule cards. With no card headings it is one chunk."""
    blocks, buf, card, fence = [], [], None, ""

    def flush():
        nonlocal buf, card
        if card is not None:
            blocks.append({"k": "rule", **finish(card, "\n".join(buf))})
        elif "".join(buf).strip():
            blocks.append({"k": "md", "text": "\n".join(buf)})
        buf, card = [], None

    for line in text.split("\n"):
        f = FENCE.match(line)
        if fence:
            if f and f.group(1)[0] == fence[0] and len(f.group(1)) >= len(fence) and not line.strip().strip(fence[0]):
                fence = ""
        elif f:
            fence = f.group(1)
        else:
            m, h = CARD.match(line), re.match(r"(#{1,6})\s", line)
            if m or (h and card is not None and len(h.group(1)) <= len(card[0])):
                flush()
                if m:
                    card = (m.group(1), m.group(2), (m.group(3) or "").strip(), re.sub(r"^#+\s*", "", line).strip())
                    continue
        buf.append(line)
    flush()
    return blocks


def finish(card, body):
    _, rid, title, heading = card
    head = next((ln for ln in body.split("\n") if ln.strip()), "")
    prio = re.search(r"\b(P\d)\b", field(body, "Priority")) or re.match(r"(P\d)-", rid) or re.match(r"[ `*]*(P\d)[ `*]*(?:·|$)", head)
    conf = re.search(r"(?i)\b(high|medium|low)\b", field(body, "Confidence")) or re.search(r"(?i)confidence:?\s*(high|medium|low)", head)
    source, defect, cat = field(body, "Source") or head, field(body, "Suspected defect"), field(body, "Category")
    body = re.sub(r"(?im)^[ \t>*-]*\**(?:Priority|Category|Source)\**[ \t]*:.*\n?", "", body).strip("\n")
    return {"id": rid, "heading": heading[:300], "title": title[:300], "p": prio.group(1).upper() if prio else "",
            "cat": re.sub(r"\s+", " ", cat)[:60], "conf": conf.group(1).capitalize() if conf else "",
            "cites": list(dict.fromkeys(CITE.findall(source)))[:12],
            "defect": bool(defect) and not re.match(r"(?i)\W*(none|n/?a|no|nil)\W*$", defect), "body": body}


def rule_facts(text, cards, reviews):
    """Priority tally: from each card, else from the index-table row that carries its id."""
    rated = {}
    for _, _, rows in tables(text):
        for row in rows:
            m, p = re.search(ID, row[0]) if row else None, next((c for c in row if re.fullmatch(r"P\d", c)), None)
            if m and p:
                rated.setdefault(m.group(0), p)
    counts = collections.Counter(c["p"] or rated.get(c["id"], "") for c in cards)
    unrated = counts.pop("", 0)
    out = {"total": len(cards), "byPriority": dict(sorted(counts.items())), "unrated": unrated, "defects": sum(1 for c in cards if c["defect"])}
    if reviews:
        out["reviews"] = dict(collections.Counter(str(v.get("verdict", "?"))[:20] for v in reviews.values() if isinstance(v, dict)))
    return out


def security_facts(text):
    """Severity tally from the findings table; a summary scorecard only when there is no findings table."""
    finds, score = collections.Counter(), collections.Counter()
    for head, header, rows in tables(text):
        low = [h.lower() for h in header]
        sev = next((i for i, h in enumerate(low) if "severity" in h), None)
        if sev is None or any(re.search(r"package|installed|fixed", h) for h in low) or \
                re.search(r"coverage|not judged|unverified|dependenc|cve|patch review|remediation", head, re.I):
            continue
        count = next((i for i, h in enumerate(low) if h in ("count", "total", "n", "#", "findings")), None)
        for row in rows:
            m = re.match(r"(?i)(critical|high|medium|low)\b", row[sev] if sev < len(row) else "")
            if m and count is not None and len(header) <= 3 and count < len(row) and row[count].isdigit():
                score[m.group(1).capitalize()] += int(row[count])
            elif m:
                finds[m.group(1).capitalize()] += 1
    return dict(finds or score) or None


def baseline_facts(text):
    """Pass/fail/skip counts from a per-test result column, or from a sentence like '12 passed, 1 failed'."""
    words, counts = {"pass": "pass", "passed": "pass", "passing": "pass", "ok": "pass", "fail": "fail", "failed": "fail",
                     "failing": "fail", "skip": "skip", "skipped": "skip", "ignored": "skip"}, collections.Counter()
    for _, header, rows in tables(text):
        col = next((i for i, h in enumerate(header) if re.search(r"result|status|outcome|verdict|passed", h, re.I)), None)
        for row in rows if col is not None else []:
            if col < len(row) and row[col].lower() in words:
                counts[words[row[col].lower()]] += 1
    for key, pat in (() if counts else (("pass", r"(\d+)\s+(?:tests?\s+|cases?\s+)?(?:passed|passing)|(?:passed|passing)\s*[:=]\s*(\d+)"),
                                        ("fail", r"(\d+)\s+(?:tests?\s+|cases?\s+)?(?:failed|failing)|(?:failed|failing)\s*[:=]\s*(\d+)"))):
        m = re.search(r"(?i)" + pat, text)
        if m:
            counts[key] = int(m.group(1) or m.group(2))
    target_only = bool(re.search(r"(?im)^\W*target-only:", text))
    return {**counts, "targetOnly": target_only} if counts or target_only else None


def topology_facts(obj):
    nodes = []

    def walk(n, depth):
        if isinstance(n, dict) and depth < 12:
            nodes.append(n)
            for c in n.get("children") or []:
                walk(c, depth + 1)

    if isinstance(obj, dict):
        walk(obj.get("root"), 0)
    mods = [n for n in nodes if n.get("kind") == "module"] or [n for n in nodes if not n.get("children") and n.get("file") and isinstance(n.get("loc"), int)]
    if not mods:
        return None
    seen = obj.get("observations")
    return {"modules": len(mods), "loc": sum(n["loc"] for n in mods if isinstance(n.get("loc"), int) and n["loc"] > 0),
            "languages": sorted({str(n["language"])[:20] for n in mods if isinstance(n.get("language"), str)})[:6],
            "edges": len(obj["edges"]) if isinstance(obj.get("edges"), list) else None,
            "observations": [str(o)[:600] for o in seen[:12]] if isinstance(seen, list) else []}


VERDICTS = ("same", "differs", "differs-approved", "missing")


def endpoint(o):
    return {k: str(o.get(k) or "")[:300] for k in ("label", "command")} if isinstance(o, dict) else {"label": "", "command": ""}


def equivalence_view(obj):
    """Tally the verdicts from the case list itself: the file's own totals and wording are never trusted."""
    if not isinstance(obj, dict) or not isinstance(obj.get("cases"), list):
        return None
    problems, tally, rows = [], collections.Counter(), []
    for c in (c for c in obj["cases"] if isinstance(c, dict)):
        s = lambda k, n=300: str(c.get(k) or "")[:n]  # noqa: E731
        masked = [str(m)[:200] for m in c["masked"][:20]] if isinstance(c.get("masked"), list) else []
        ld, nd = (d if re.fullmatch(r"[0-9a-f]{64}", d) else "" for d in (s("legacySha256", 80), s("newSha256", 80)))
        v = s("verdict", 30) if s("verdict", 30) in VERDICTS else "unknown"
        if v == "same" and (c.get("firstDiff") or (not masked and ld and nd and ld != nd)) or (v == "differs-approved" and not s("approvedDifference").strip()):
            v = "inconsistent"
        tally[v] += 1
        row = {"id": s("id", 80), "title": s("title"), "verdict": v, "reason": s("reason", 500), "legacyPath": s("legacyPath"), "newPath": s("newPath"),
               "legacySha256": s("legacySha256", 80), "newSha256": s("newSha256", 80), "masked": masked,
               "approvedDifference": s("approvedDifference", 500), "note": s("note", 500), "empty": c.get("empty") is True}
        if isinstance(c.get("firstDiff"), dict):
            fd = c["firstDiff"]
            row["firstDiff"] = {k: fd[k] if isinstance(fd.get(k), int) else 0 for k in ("offset", "line", "at")}
            row["firstDiff"].update({k: str(fd.get(k) or "")[:120] for k in ("legacy", "new")})
        if isinstance(c.get("bytes"), dict) and isinstance(c.get("maskedBytes"), dict):
            row["sizes"] = {k: [c["bytes"].get(k), c["maskedBytes"].get(k)] for k in ("legacy", "new") if isinstance(c["bytes"].get(k), int) and isinstance(c["maskedBytes"].get(k), int)}
        if v == "inconsistent":
            problems.append("Case %s: the recorded verdict contradicts its own evidence, so it counts as a failure." % row["id"])
        rows.append(row)
    ran = ("same", "differs", "differs-approved", "inconsistent")
    executed, bad = sum(tally[k] for k in ran), tally["differs"] + tally["missing"] + tally["inconsistent"] + tally["unknown"]
    sc = obj["selfCheck"] if isinstance(obj.get("selfCheck"), dict) else None
    check = {"passed": sc["passed"] if sc and isinstance(sc.get("passed"), bool) else None, "detail": str(sc.get("detail") or "")[:300] if sc else "", "recorded": sc is not None}
    if not sc:
        problems.append("No self-check is recorded, so this file may not have been written by scripts/compare.py.")
    declared = obj["totals"] if isinstance(obj.get("totals"), dict) else {}
    if declared and (declared.get("cases") != len(rows) or declared.get("executed") != executed):
        problems.append("The totals stored in the file disagree with its case list; the case list was used.")
    empty = executed > 0 and all(r["empty"] for r in rows if r["verdict"] in ran)
    if executed == 0:
        headline = "Equivalence not proven: no case was executed."
    elif empty:
        headline = "Equivalence not proven: every compared output was empty."
    elif bad or check["passed"] is False:
        why = ["%d %s" % (tally[k], w) for k, w in (("differs", "differing"), ("missing", "missing"), ("inconsistent", "contradictory"), ("unknown", "unrecognised")) if tally[k]]
        headline = "Equivalence not proven: %s%s (%d of %d cases executed)." % (
            ", ".join(why) or "no case failed", "; the comparator's self-check failed" if check["passed"] is False else "", executed, len(rows))
    else:
        approved = tally["differs-approved"]
        headline = "Outputs match on all %d executed cases%s." % (executed, " (%d with a difference a person approved)" % approved if approved else "")
    return {"state": "red" if (executed == 0 or empty or bad or check["passed"] is False) else "green", "headline": headline, "problems": problems,
            "selfCheck": check, "generated": str(obj.get("generated") or "")[:40], "tally": {"cases": len(rows), "executed": executed, **dict(tally)},
            "legacy": endpoint(obj.get("legacy")), "new": endpoint(obj.get("new")), "cases": rows[:MAX_CASES], "cut": max(0, len(rows) - MAX_CASES)}


# ---------------------------------------------------------------- assembling the report
def nonempty_dir(p):
    try:
        return os.path.isdir(p) and bool(os.listdir(p))
    except OSError:
        return False


def newest(paths):
    """(mtime, path) of the newest existing file, or non-empty folder, among `paths`."""
    best = None
    for p in paths:
        try:
            if os.path.islink(p) or (os.path.isdir(p) and not nonempty_dir(p)):
                continue
            times = [os.stat(p).st_mtime] + ([e.stat().st_mtime for e in os.scandir(p)] if os.path.isdir(p) else [])
        except OSError:
            continue
        best = max(best, (max(times), p)) if best else (max(times), p)
    return best


def modernized_docs(src):
    """(label, text) for the notes files of modernized/<system>{,-uplifted,-reimagined}, one folder level down."""
    out, skipped = [], 0
    for suffix in ("", "-uplifted", "-reimagined"):
        base = os.path.join(src.mdir, src.system + suffix)
        try:
            folders = [base] + sorted(e.path for e in os.scandir(base) if e.is_dir(follow_symlinks=False))[:200]
        except OSError:
            continue
        for folder in folders:
            for name in NOTE_NAMES:
                path = os.path.join(folder, name)
                label = os.path.relpath(path, src.mdir).replace(os.sep, "/")
                if len(out) >= MAX_NOTES and os.path.lexists(path):
                    skipped += 1
                    continue
                text = src.read(path, "modernized/" + label)
                if text is not None:
                    out.append((label, text))
    if skipped:
        src.notes.append("%d more notes files under modernized/ are not included (limit %d)." % (skipped, MAX_NOTES))
    return out


def load_mermaid(src):
    try:
        with open(os.path.join(ASSETS, "vendor", "mermaid.min.js"), encoding="utf-8") as fh:
            return fh.read().replace("</script", "<\\/script").replace("<!--", "<\\!--")
    except OSError:
        src.notes.append("The Mermaid library was not found next to the template, so diagrams are shown as source.")
        return ""


def build(system, workspace, out=None):
    """-> (html, section count, output path), or None when nothing was found."""
    src = Source(workspace, system)
    out = os.path.abspath(out or os.path.join(src.adir, "REPORT.html"))
    a = lambda name: os.path.join(src.adir, name)  # noqa: E731
    parts, texts, docs = {k: [] for k, _ in TITLES}, [], {}
    reviews, _ = src.json(a("RULE_REVIEWS.json"), "RULE_REVIEWS.json")
    reviews = {k: v for k, v in reviews["reviews"].items() if isinstance(v, dict)} if isinstance(reviews, dict) and isinstance(reviews.get("reviews"), dict) else {}
    glance = {"rules": None, "security": None, "baseline": None, "topology": None, "equivalence": None}

    for key, names in DOCS:
        for name in names:
            text = src.read(a(name), name)
            if text is None:
                continue
            docs[name] = text
            blocks = parse_rules(text) if name == "BUSINESS_RULES.md" else []
            cards = [b for b in blocks if b["k"] == "rule"]
            if cards:
                glance["rules"] = rule_facts(text, cards, reviews)
                parts[key].append({"t": "rules", "name": name, "blocks": blocks, "reviews": {k: str(v.get("verdict", ""))[:20] for k, v in reviews.items()}})
            else:
                parts[key].append({"t": "md", "name": name, "text": text})
    texts += docs.values()
    glance["security"] = security_facts(docs["SECURITY_FINDINGS.md"]) if "SECURITY_FINDINGS.md" in docs else None
    glance["baseline"] = baseline_facts(docs["BASELINE.md"]) if "BASELINE.md" in docs else None

    topo, topo_seen = src.json(a("topology.json"), "topology.json")
    t = glance["topology"] = topology_facts(topo)
    try:
        names = sorted(e.name for e in os.scandir(src.adir) if e.name.lower().endswith(".mmd"))
    except OSError:
        names = []
    figures = [{"name": n, "src": text} for n in names for text in [src.read(a(n), n)] if text is not None]
    texts += [f["src"] for f in figures]
    if t:
        parts["diagrams"].append({"t": "facts", "items": [["Modules", num(t["modules"])], ["Lines of code", num(t["loc"])]] + (
            [["Dependencies", num(t["edges"])]] if t["edges"] is not None else []) + ([["Languages", ", ".join(t["languages"])]] if t["languages"] else [])})
    html_map = a("TOPOLOGY.html")
    has_map = os.path.isfile(html_map) and not os.path.islink(html_map)
    if has_map:
        src.found.append(("TOPOLOGY.html", os.path.getsize(html_map), utc_day(os.path.getmtime(html_map))))
        try:
            rel = quote(os.path.relpath(html_map, os.path.dirname(out)).replace(os.sep, "/"), safe="/")
            parts["diagrams"].append({"t": "link", "href": rel, "text": "Open the interactive map (TOPOLOGY.html, kept as a separate file)"})
        except ValueError:
            pass
    if t and t["observations"]:
        parts["diagrams"].append({"t": "list", "title": "What the map found", "items": t["observations"]})
    if figures:
        parts["diagrams"].append({"t": "figures", "items": figures})

    for label, text in modernized_docs(src):
        texts.append(text)
        parts["build"].append({"t": "md", "name": "modernized/" + label, "text": text})

    eq, eq_seen = src.json(a("EQUIVALENCE.json"), "EQUIVALENCE.json")
    if eq_seen:
        view = equivalence_view(eq)
        if view:
            parts["equivalence"].append({"t": "equiv", "eq": view})
            glance["equivalence"] = {k: view[k] for k in ("state", "headline", "problems", "tally")}
        else:
            glance["equivalence"] = {"state": "red", "headline": "EQUIVALENCE.json could not be used, so equivalence is not proven.", "problems": [], "tally": None}
            parts["equivalence"].append({"t": "p", "text": glance["equivalence"]["headline"]})

    mods = [os.path.join(src.mdir, system + s) for s in ("", "-uplifted", "-reimagined")]
    done = {"preflight": "PREFLIGHT.md" in docs, "assess": "ASSESSMENT.md" in docs, "rules": "BUSINESS_RULES.md" in docs, "brief": "MODERNIZATION_BRIEF.md" in docs,
            "map": topo is not None or has_map or any(f["name"] != "ARCHITECTURE.mmd" for f in figures), "build": any(nonempty_dir(p) for p in mods), "harden": "SECURITY_FINDINGS.md" in docs}
    glance["steps"] = [{"key": k, "label": label, "done": bool(done[k])} for k, label in STEPS]
    tracks = {"rewrite": [mods[0]], "same-stack uplift": [a("DELTA_CATALOG.md"), a("PLAYBOOK.md"), mods[1]], "reimagine": [a("AI_NATIVE_SPEC.md"), a("REIMAGINED_ARCHITECTURE.md"), mods[2]]}
    ranked = sorted(((newest(p), k) for k, p in tracks.items() if newest(p)), reverse=True)
    glance["track"] = {"label": ranked[0][1], "why": "newest artifact: " + os.path.relpath(ranked[0][0][1], workspace).replace(os.sep, "/")} if ranked else None
    if not src.found:
        return None

    lib = load_mermaid(src) if figures or any(MERMAID_FENCE.search(x) for x in texts) else ""
    parts["overview"].insert(0, {"t": "table", "head": ["Artifact", "Size", "Modified"], "rows": [[n, "%s KB" % num(s >> 10) if s >= 1024 else "%d B" % s, m] for n, s, m in sorted(src.found)]})
    if src.notes:
        parts["overview"].insert(0, {"t": "list", "title": "Notes about this report", "items": src.notes})
    sections = [{"id": k, "title": title, "parts": parts[k]} for k, title in TITLES if parts[k]]
    data = {"v": 1, "system": system[:200], "generated": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC"), "glance": glance, "sections": sections}
    return render(data, lib), len(sections), out


def script_json(data):
    """JSON that can sit inside a <script> element: no <, > or & appears in it, so </script> and <!-- cannot."""
    return json.dumps(data, ensure_ascii=True, separators=(",", ":")).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


def render(data, lib):
    with open(os.path.join(ASSETS, "report-template.html"), encoding="utf-8") as fh:
        template = fh.read().replace("\r\n", "\n")
    app = re.search(r'<script id="app">(.*?)</script>', template, re.S).group(1)
    sha = lambda text: "'sha256-%s'" % base64.b64encode(hashlib.sha256(text.encode("utf-8")).digest()).decode()  # noqa: E731
    policy = "default-src 'none'; script-src %s; style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'" % " ".join([sha(app)] + ([sha(lib)] if lib else []))
    fill = {"CSP": policy, "DATA": script_json(data), "MERMAID": '<script id="mermaid-lib">%s</script>' % lib if lib else ""}
    return re.sub(r"@@(CSP|DATA|MERMAID)@@", lambda m: fill[m.group(1)], template)


def write_atomic(path, data):
    """Write `data` to a temp file beside `path`, then rename it over `path`.
    Returns why it refused (a symlinked path or folder), or None once written."""
    folder = os.path.dirname(path)
    for p in (path, folder):
        if os.path.islink(p):
            return "refusing to write through a symbolic link: %s" % p
    os.makedirs(folder, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=folder, prefix=".report-", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        umask = os.umask(0)
        os.umask(umask)
        os.chmod(tmp, 0o666 & ~umask)
        os.replace(tmp, path)
    except BaseException:
        if os.path.lexists(tmp):
            os.unlink(tmp)
        raise
    return None


def main(argv=None):
    ap = argparse.ArgumentParser(description="Build a self-contained HTML report from a system's modernization artifacts.")
    ap.add_argument("system", help="the system's folder name under analysis/")
    ap.add_argument("--workspace", default=".", help="the project root holding analysis/ and modernized/ (default: current folder)")
    ap.add_argument("--out", help="where to write the report (default: <workspace>/analysis/<system>/REPORT.html)")
    args = ap.parse_args(argv)
    if not args.system or args.system in (".", "..") or re.search(r"[\\/\x00]", args.system):
        print("build_report.py: the system must be a folder name under analysis/, not a path", file=sys.stderr)
        return 2
    try:
        result = build(args.system, args.workspace, args.out)
    except OSError as err:
        print("build_report.py: %s" % err, file=sys.stderr)
        return 1
    if result is None:
        print("build_report.py: nothing found for %r under %s (analysis/ or modernized/)" % (args.system, os.path.abspath(args.workspace)), file=sys.stderr)
        return 1
    html, count, path = result
    try:
        refused = write_atomic(path, html.encode("utf-8"))
    except OSError as err:
        refused = "could not write %s (%s)" % (path, err.__class__.__name__)
    if refused:
        print("build_report.py: %s" % refused, file=sys.stderr)
        return 1
    print("%s: %d section%s, %s KB" % (path, count, "" if count == 1 else "s", num(os.path.getsize(path) >> 10)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
