---
description: Dependency & topology mapping — call graphs, data lineage, batch flows, rendered as navigable diagrams
argument-hint: <system-dir>
---

Build a **dependency and topology map** of `legacy/$1` and render it visually.

The assessment gave us domains. Now go one level deeper: how do the *pieces*
connect? This is the map an engineer needs before touching anything.

## What to produce

Write a one-off analysis script (Python or shell — your choice) that parses
the source under `legacy/$1` and extracts:

- **Program/module call graph** — who calls whom (for COBOL: `CALL` statements
  and CICS `LINK`/`XCTL`; for Java: class-level imports/invocations; for Node:
  `require`/`import`)
- **Data dependency graph** — which programs read/write which data stores
  (COBOL: copybooks + VSAM/DB2 in JCL DD statements; Java: JPA entities/tables;
  Node: model files)
- **Entry points** — batch jobs, transaction IDs, HTTP routes, CLI commands
- **Dead-end candidates** — modules with no inbound edges (potential dead code)

Save the script as `analysis/$1/extract_topology.py` (or `.sh`) so it can be
re-run and audited. Run it. Show the raw output.

## Render

From the extracted data, generate **three Mermaid diagrams** and write them
to `analysis/$1/TOPOLOGY.html` as a self-contained page that renders in any
browser.

The HTML page must use: dark `#1e1e1e` background, `#d4d4d4` text,
`#cc785c` for `<h2>`/accents, `system-ui` font, all CSS **inline** (no
external stylesheets). Load Mermaid from a CDN in `<head>`:

```html
<script type="module">
  import mermaid from 'https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.esm.min.mjs';
  mermaid.initialize({ startOnLoad: true, theme: 'dark' });
</script>
```

Each diagram goes in a `<pre class="mermaid">...</pre>` block. Do **not**
wrap diagrams in markdown ` ``` ` fences inside the HTML.

1. **`graph TD` — Module call graph.** Cluster by domain (use `subgraph`).
   Highlight entry points in a distinct style. Cap at ~40 nodes — if larger,
   show domain-level with one expanded domain.

2. **`graph LR` — Data lineage.** Programs → data stores.
   Mark read vs write edges.

3. **`flowchart TD` — Critical path.** Trace ONE end-to-end business flow
   (e.g., "monthly billing run" or "process payment") through every program
   and data store it touches, in execution order. If production telemetry is
   available (see `/modernize-assess` Step 4), annotate each step with its
   p50/p99 wall-clock.

Also export the three diagrams as standalone `.mmd` files for re-use:
`analysis/$1/call-graph.mmd`, `analysis/$1/data-lineage.mmd`,
`analysis/$1/critical-path.mmd`.

## Annotate

Below each `<pre class="mermaid">` block in TOPOLOGY.html, add a `<ul>`
with 3-5 **architect observations**: tight coupling clusters, single
points of failure, candidates for service extraction, data stores
touched by too many writers.

## Present

Tell the user to open `analysis/$1/TOPOLOGY.html` in a browser.
