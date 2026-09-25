import { baseName } from '../paths'
import { unitOfPath } from '../reader/estate-model'
import type { Snapshot } from '../reader/progress'
import type { Rule } from '../reader/rules'
import { stateWord } from '../map/estate'
import { baselineKeyOf } from '../reader/uplift'
import { nodeOfFile, type TopoNode, type Topology } from '../reader/topology'

/**
 * X-ray reads: when the model reads a legacy file, what the analysis stages
 * already worked out about that file rides along as context the model reads
 * and the person never sees. Every line is lifted from an artifact on disk.
 */

export type XrayRequest = {
  /** The file read, relative to `legacy/<system>/`. */
  fileRel: string
  /** First line read (1-based) and how many, when the read was a window. */
  offset?: number
  limit?: number
}

export type XrayNote = {
  text: string
  /** One short line for the status bar. */
  summary: string
  rules: number
  node: string | null
}

/** Keeps a note well inside the 32,000-character cap a call's context has. */
const MAX_CHARS = 2400
const MAX_RULES = 9
const MAX_NAMES = 8

const some = (names: string[], max = MAX_NAMES): string =>
  names.length <= max ? names.join(', ') : `${names.slice(0, max).join(', ')} +${names.length - max} more`

const nameOf = (topo: Topology, id: string): string => topo.byId.get(id)?.name ?? id

function edgesOf(topo: Topology, node: TopoNode) {
  const incoming = topo.edges.filter(edge => edge.target === node.id)
  const outgoing = topo.edges.filter(edge => edge.source === node.id)
  const isCode = (kind: string) => kind === 'call' || kind === 'dispatch' || kind === 'uses'
  const uniq = (ids: string[]) => [...new Set(ids)].map(id => nameOf(topo, id))

  return {
    callers: uniq(incoming.filter(edge => isCode(edge.kind)).map(edge => edge.source)),
    callees: uniq(outgoing.filter(edge => isCode(edge.kind)).map(edge => edge.target)),
    reads: uniq(outgoing.filter(edge => edge.kind === 'read').map(edge => edge.target)),
    writes: uniq(outgoing.filter(edge => edge.kind === 'write').map(edge => edge.target)),
  }
}

const rank = (rule: Rule): number =>
  (rule.priority === 'P0' ? 0 : rule.priority === 'P1' ? 1 : 2) * 2 + (rule.defect !== undefined ? 0 : 1)

function ruleLine(rule: Rule, base: string): string {
  const spans = rule.citations
    .filter(citation => citation.base === base)
    .slice(0, 2)
    .map(citation => (citation.from === citation.to ? `L${citation.from}` : `L${citation.from}-${citation.to}`))

  const flags = [
    rule.defect !== undefined ? 'suspected defect' : '',
    rule.sme !== undefined ? 'needs SME' : '',
    rule.confidence !== undefined && rule.confidence !== 'High' ? `${rule.confidence} confidence` : '',
  ].filter(flag => flag !== '')

  const label = rule.id.startsWith('R-') ? rule.priority || 'rule' : rule.id

  return `- ${label} ${rule.title}${spans.length > 0 ? ` (${spans.join(', ')})` : ''}${flags.length > 0 ? ` [${flags.join('; ')}]` : ''}`
}

/**
 * What an uplift already knows about a file: which module it is in, what that module's baseline was on the
 * source runtime (the failures there are part of the oracle), where the module stands in the working copy, and
 * which deltas the catalog cites the file under.
 */
function upliftXray(snapshot: Snapshot, request: XrayRequest): XrayNote | null {
  const estate = snapshot.estate
  const unit = estate !== null ? unitOfPath(estate, null, request.fileRel) : null
  const deltas = snapshot.uplift?.catalog?.byFileBase.get(baseName(request.fileRel).toLowerCase()) ?? []
  const row = unit?.dir !== undefined ? (snapshot.uplift?.baseline?.rows.get(baselineKeyOf(unit.dir)) ?? null) : null
  const module = unit !== null ? snapshot.byNode.get(unit.id) : undefined

  if (deltas.length === 0 && row === null && module === undefined) {
    return null
  }

  const lines = [
    `[x-ray for ${request.fileRel}${unit !== null ? ` · ${unit.dir === '' || unit.dir === undefined ? unit.name : unit.dir}` : ''} · uplift] (from analysis/${snapshot.system}/; facts already established, do not re-derive)`,
  ]

  if (row !== null) {
    lines.push(
      `Baseline on the source runtime: ${row.pass} pass, ${row.fail} fail, ${row.error} error, ${row.skip} skip. What fails there is part of the oracle: reproduce it, do not fix it.`,
    )
  }

  if (module !== undefined) {
    const tests = module.tests

    lines.push(
      `In the working copy: ${stateWord('uplift', module.state)}${tests !== null ? ` (${tests.tests} tests, ${tests.failures + tests.errors} failing)` : ''}.`,
    )
  }

  if (deltas.length > 0) {
    lines.push(`The delta catalog cites this file under ${some(deltas, 6)}.`)
  }

  return {
    text: lines.join('\n'),
    summary: `x-ray ${baseName(request.fileRel)}: ${deltas.length} delta${deltas.length === 1 ? '' : 's'}${row !== null ? ', baseline' : ''}`,
    rules: 0,
    node: unit?.id ?? null,
  }
}

/** Builds the note for one read; null when the artifacts know nothing about the file. */
export function xrayOf(snapshot: Snapshot, request: XrayRequest): XrayNote | null {
  if (snapshot.track === 'uplift') {
    return upliftXray(snapshot, request)
  }

  const base = baseName(request.fileRel).toLowerCase()
  const topo = snapshot.topology
  const node = topo !== null ? nodeOfFile(topo, request.fileRel) : null
  const cited = snapshot.rules?.byFileBase.get(base) ?? []

  if (node === null && cited.length === 0) {
    return null
  }

  const lines: string[] = []
  const head = [`x-ray for ${request.fileRel}`]

  if (node !== null) {
    head.push(node.name)

    if (node.domain !== undefined) {
      head.push(node.domain)
    }

    if (node.loc > 0) {
      head.push(`${node.loc} lines`)
    }
  }

  lines.push(`[${head.join(' · ')}] (from analysis/${snapshot.system}/; facts already established, do not re-derive)`)

  if (topo !== null && node !== null) {
    const edges = edgesOf(topo, node)
    const roles: string[] = []

    if (topo.entryPoints.has(node.id)) {
      roles.push('an entry point')
    }

    if (topo.deadEnds.has(node.id)) {
      roles.push('flagged as a dead end by the map')
    }

    if (roles.length > 0) {
      lines.push(`Role: ${roles.join(', ')}.`)
    }

    if (edges.callers.length > 0) {
      lines.push(`Reached from: ${some(edges.callers)}.`)
    } else if (!topo.entryPoints.has(node.id) && node.kind === 'module') {
      lines.push('Reached from: nothing the map found (check dynamic dispatch before calling it dead).')
    }

    if (edges.callees.length > 0) {
      lines.push(`Calls: ${some(edges.callees)}.`)
    }

    if (edges.reads.length > 0) {
      lines.push(`Reads: ${some(edges.reads)}.`)
    }

    if (edges.writes.length > 0) {
      lines.push(`Writes: ${some(edges.writes)}.`)
    }

    const flows = topo.flows.filter(flow => flow.steps.some(step => step.nodes.includes(node.id)))

    if (flows.length > 0) {
      lines.push(`Business flows through it: ${some(flows.map(flow => `"${flow.name}"`), 4)}.`)
    }
  }

  if (cited.length > 0) {
    const p0 = cited.filter(rule => rule.priority === 'P0').length
    const from = request.offset
    const to = from !== undefined && request.limit !== undefined ? from + request.limit - 1 : undefined

    const inWindow =
      from !== undefined && to !== undefined
        ? cited.filter(rule =>
            rule.citations.some(
              citation => citation.base === base && citation.from <= to && citation.to >= from,
            ),
          )
        : []

    const shown = (inWindow.length > 0 ? inWindow : [...cited]).sort((a, b) => rank(a) - rank(b)).slice(0, MAX_RULES)

    lines.push(
      `Business rules citing this file: ${cited.length}${p0 > 0 ? ` (${p0} P0)` : ''}, in analysis/${snapshot.system}/BUSINESS_RULES.md.${inWindow.length > 0 ? ` In the lines just read (${from}-${to}):` : ' Highest priority first:'}`,
    )

    for (const rule of shown) {
      lines.push(ruleLine(rule, base))
    }

    const rest = (inWindow.length > 0 ? inWindow.length : cited.length) - shown.length

    if (rest > 0) {
      lines.push(`- and ${rest} more.`)
    }

    const verdicts = cited
      .map(rule => ({ rule, review: snapshot.reviews[rule.id] }))
      .filter(entry => entry.review !== undefined && entry.review.verdict !== 'confirmed')

    if (verdicts.length > 0) {
      lines.push(
        `A reviewer disputed: ${some(verdicts.map(entry => `${entry.rule.id} (${entry.review?.verdict})`), 6)}. Do not treat those as settled.`,
      )
    }
  }

  const unitId = node?.id ?? (snapshot.estate !== null ? unitOfPath(snapshot.estate, topo, request.fileRel)?.id : undefined)

  if (unitId !== undefined) {
    const module = snapshot.byNode.get(unitId)

    if (module !== undefined) {
      const tests = module.tests

      lines.push(
        `Already transformed at ${module.path}: ${module.state.replace('-', ' ')}${tests !== null ? `, ${tests.tests - tests.failures - tests.errors}/${tests.tests} tests passing` : ''}.`,
      )
    }
  }

  let text = lines.join('\n')

  if (text.length > MAX_CHARS) {
    text = `${text.slice(0, MAX_CHARS - 40).replace(/\n[^\n]*$/, '')}\n- (note trimmed)`
  }

  const callers = topo !== null && node !== null ? edgesOf(topo, node).callers.length : 0

  return {
    text,
    summary: `x-ray ${node?.name ?? baseName(request.fileRel)}: ${cited.length} rule${cited.length === 1 ? '' : 's'}${callers > 0 ? `, ${callers} caller${callers === 1 ? '' : 's'}` : ''}`,
    rules: cited.length,
    node: node?.id ?? null,
  }
}
