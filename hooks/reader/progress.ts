import { join } from '../paths'
import { parseBrief, type Brief, type Phase } from './brief'
import { discoverEstate, sourceSizes } from './discover'
import { estateOfTopology, keysOfUnit, type EstateModel, type EstateUnit } from './estate-model'
import { listOrEmpty, mtimeOrNull, readOrNull, type ReaderFs } from './fs'
import { isDone, readModernizedIn, type ModernizedModule, type TestTotals } from './modernized'
import { needsReview, parseRules, type RuleSet } from './rules'
import { pickTrack, TRACK_LABELS, type TrackKey } from './tracks'
import { parseTopology, type Topology } from './topology'
import {
  changedUnitsOf,
  parseBaseline,
  parseCatalog,
  changedPathsOf,
  readUpliftUnits,
  type Baseline,
  type Catalog,
} from './uplift'

/**
 * One reading of a system's modernization state, from the artifacts on disk
 * alone. Everything here is a fact of a file that exists; nothing is inferred
 * by a model, and what cannot be read is absent.
 */

export type StageKey =
  | 'preflight'
  | 'assess'
  | 'map'
  | 'rules'
  | 'brief'
  | 'transform'
  | 'harden'
  | 'deltas'
  | 'baseline'
  | 'pilot'
  | 'migrate'
  | 'verify'
  | 'spec'
  | 'design'
  | 'scaffold'
  | 'tests'

export type Stage = {
  key: StageKey
  label: string
  isDone: boolean
  mtimeMs: number | null
  /** One short qualifier (`signed`, `319 rules`), when there is one. */
  detail?: string
}

export type ReviewVerdict = 'confirmed' | 'wrong' | 'discuss'

export type ReviewLedger = Record<
  string,
  { verdict: ReviewVerdict; at: string; title?: string; note?: string }
>

export type NextStep = {
  /** The slash command to run, or what to do by hand. */
  text: string
  isByHand: boolean
  reason: string
}

/** What an uplift has left on disk, beyond the modules it changed. */
export type UpliftFacts = {
  catalog: Catalog | null
  baseline: Baseline | null
  hasPlaybook: boolean
  hasNotes: boolean
  hasCopy: boolean
  /** Whether the working copy's changes could be read (a version-control status), or only its test reports. */
  isChangeKnown: boolean
}

export type Snapshot = {
  system: string
  systems: string[]
  /** Which way the plugin's commands are working on the system. */
  track: TrackKey
  /** True once the system has any artifact under `analysis/`: modernization is under way, not only possible. */
  hasAnalysis: boolean
  stages: Stage[]
  /** The units the estate map draws: the map's modules, or what the legacy tree holds. */
  estate: EstateModel | null
  topology: Topology | null
  rules: RuleSet | null
  brief: Brief | null
  /** The units of work under way: transformed modules, uplifted modules, or reimagined services. */
  modules: ModernizedModule[]
  /** Estate unit id to its unit of work, where one matches. */
  byNode: Map<string, ModernizedModule>
  /** Units of work that match no unit of the estate. */
  extras: ModernizedModule[]
  uplift: UpliftFacts | null
  findings: { exists: boolean; isScan: boolean }
  reviews: ReviewLedger
  /** Size of the units finished over the estate's total; null without an estate, or where units of work are not the estate's own. */
  percent: number | null
  totals: { modules: number; done: number; loc: number; locDone: number }
  attention: string[]
  next: NextStep | null
  readAtMs: number
}

export const STAGE_LABELS: Record<StageKey, string> = {
  preflight: 'preflight',
  assess: 'assess',
  map: 'map',
  rules: 'rules',
  brief: 'brief',
  transform: 'transform',
  harden: 'harden',
  deltas: 'deltas',
  baseline: 'baseline',
  pilot: 'pilot',
  migrate: 'migrate',
  verify: 'verify',
  spec: 'spec',
  design: 'design',
  scaffold: 'scaffold',
  tests: 'tests',
}

const STAGE_FILES = {
  preflight: 'PREFLIGHT.md',
  assess: 'ASSESSMENT.md',
  map: 'topology.json',
  rules: 'BUSINESS_RULES.md',
  brief: 'MODERNIZATION_BRIEF.md',
  transform: 'TRANSFORMATION_NOTES.md',
  harden: 'SECURITY_FINDINGS.md',
  deltas: 'DELTA_CATALOG.md',
  baseline: 'BASELINE.md',
  pilot: 'PLAYBOOK.md',
  spec: 'AI_NATIVE_SPEC.md',
  design: 'REIMAGINED_ARCHITECTURE.md',
} as const

export const REVIEWS_FILE = 'RULE_REVIEWS.json'

/** Parsed files kept by path and mtime, so an unchanged file is parsed once. */
export type ReaderCache = Map<string, { mtimeMs: number; value: unknown }>

async function cached<T>(
  fs: ReaderFs,
  cache: ReaderCache,
  path: string,
  parse: (text: string) => T,
): Promise<{ value: T | null; mtimeMs: number | null }> {
  const mtimeMs = await mtimeOrNull(fs, path)

  if (mtimeMs === null) {
    cache.delete(path)

    return { value: null, mtimeMs: null }
  }

  const hit = cache.get(path)

  if (hit !== undefined && hit.mtimeMs === mtimeMs) {
    return { value: hit.value as T, mtimeMs }
  }

  const text = await readOrNull(fs, path)

  if (text === null) {
    return { value: null, mtimeMs }
  }

  const value = parse(text)

  cache.set(path, { mtimeMs, value })

  return { value, mtimeMs }
}

/** The systems the workspace holds: each directory under `analysis/` and under the legacy tree. */
export async function systemsOf(fs: ReaderFs, legacyDir = 'legacy'): Promise<string[]> {
  const names = new Set<string>()

  for (const root of ['analysis', legacyDir]) {
    for (const entry of await listOrEmpty(fs, root)) {
      if (entry.kind === 'dir' && !entry.name.startsWith('.')) {
        names.add(entry.name)
      }
    }
  }

  return [...names].sort()
}

const slugOf = (target: string) =>
  target
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')

/** How a transformed directory's name is matched to a unit's names. */
const keyOf = (name: string) => name.toLowerCase().replace(/::/g, '-').replace(/[^a-z0-9]+/g, '-')

function approvedPhases(brief: Brief): Phase[] {
  if (!brief.approval.isSigned) {
    return []
  }

  const ordered = [...brief.phases].sort((a, b) => a.number - b.number)

  return brief.approval.covers === 'full' ? ordered : ordered.slice(0, 1)
}

/** Whether one unit of work is finished, by what the track counts as finished. */
export function isUnitDone(
  snapshot: Pick<Snapshot, 'track' | 'uplift'>,
  module: Pick<ModernizedModule, 'state' | 'hasNotes'>,
): boolean {
  if (snapshot.track !== 'uplift') {
    return isDone(module)
  }

  // An uplift is proven by reproducing the baseline; with no per-module baseline, passing is all there is to compare.
  const hasRows = (snapshot.uplift?.baseline?.rows.size ?? 0) > 0

  return module.state === 'reviewed' || (module.state === 'tests-green' && !hasRows)
}

function nextOfTransform(
  prefix: string,
  system: string,
  stages: Stage[],
  brief: Brief | null,
  byNode: Map<string, ModernizedModule>,
): NextStep | null {
  const done = (key: StageKey) => stages.find(stage => stage.key === key)?.isDone === true
  const cmd = (name: string, rest = '') => `${prefix}${name} ${system}${rest === '' ? '' : ` ${rest}`}`

  if (!done('preflight') && !done('assess')) {
    return { text: cmd('preflight'), isByHand: false, reason: 'check the environment before analysis' }
  }

  if (!done('assess')) {
    return { text: cmd('assess'), isByHand: false, reason: 'inventory and complexity come first' }
  }

  if (!done('map')) {
    return { text: cmd('map'), isByHand: false, reason: 'the brief and the rules both read the topology' }
  }

  if (!done('rules')) {
    return { text: cmd('extract-rules'), isByHand: false, reason: 'the behavior contract comes from the rules' }
  }

  if (!done('brief') || brief === null) {
    return { text: cmd('brief'), isByHand: false, reason: 'discovery is complete; plan the phases' }
  }

  if (!brief.approval.isSigned) {
    return {
      text: 'approve the brief: tell Claude which phases you approve',
      isByHand: true,
      reason: 'execution commands treat an unapproved brief as not approved',
    }
  }

  const target = brief.target !== undefined ? slugOf(brief.target) : ''

  for (const phase of approvedPhases(brief)) {
    const open = phase.modules.find(id => {
      const module = byNode.get(id)

      return module === undefined || !isDone(module)
    })

    if (open !== undefined) {
      return {
        text: cmd('transform', `${open}${target === '' ? '' : ` ${target}`}`),
        isByHand: false,
        reason: `Phase ${phase.number} names ${open} and it is not reviewed yet`,
      }
    }

    if (phase.modules.length === 0) {
      return {
        text: `pick Phase ${phase.number}'s first module and run ${prefix}transform ${system} <module>${target === '' ? '' : ` ${target}`}`,
        isByHand: true,
        reason: `Phase ${phase.number} names no module the map knows`,
      }
    }
  }

  return {
    text: cmd('status'),
    isByHand: false,
    reason:
      brief.approval.covers === 'full'
        ? 'every approved phase is reviewed'
        : 'Phase 1 is reviewed; its retrospective revises the brief before Phase 2 is approved',
  }
}

/** The uplift command needs both versions, which only a person knows: the hint is by hand. */
function nextOfUplift(prefix: string, system: string, stages: Stage[]): NextStep {
  const done = (key: StageKey) => stages.find(stage => stage.key === key)?.isDone === true
  const command = `${prefix}uplift ${system} <from> <to>`

  if (!done('deltas')) {
    return { text: command, isByHand: true, reason: 'the delta catalog comes first: what the target version breaks here' }
  }

  if (!done('baseline')) {
    return { text: command, isByHand: true, reason: 'record the baseline before any module is migrated: it is the equivalence target' }
  }

  if (!done('pilot')) {
    return { text: command, isByHand: true, reason: 'migrate one representative module and write the playbook before the rest' }
  }

  if (!done('verify')) {
    return { text: command, isByHand: true, reason: 'migrate the rest in batches by the playbook, then run the dual-run diff' }
  }

  return { text: `${prefix}status ${system}`, isByHand: false, reason: 'every uplift artifact is written; status checks what is stale' }
}

function nextOfReimagine(prefix: string, system: string, stages: Stage[]): NextStep {
  const done = (key: StageKey) => stages.find(stage => stage.key === key)?.isDone === true
  const command = `${prefix}reimagine ${system} <vision>`

  if (!done('spec')) {
    return { text: command, isByHand: true, reason: 'the spec is mined from the legacy code first' }
  }

  if (!done('design')) {
    return { text: command, isByHand: true, reason: 'the target architecture is designed and reviewed against the spec' }
  }

  if (!done('scaffold')) {
    return { text: command, isByHand: true, reason: 'scaffold each service from the approved architecture' }
  }

  return { text: `${prefix}status ${system}`, isByHand: false, reason: 'the services are scaffolded; status checks what is stale' }
}

export type ReadOptions = {
  /** The system to read; the first one found when absent or unknown. */
  system?: string
  /** What a command is written with, up to its verb (`/code-modernization:modernize-`). */
  commandPrefix: string
  nowMs: number
  /** The read-only tree holding the systems, relative to the workspace; `legacy` when absent. */
  legacyDir?: string
  /** Which way to follow the system; `auto` when absent: whichever one's artifacts are newest. */
  track?: TrackKey | 'auto'
  /** Units of an uplift's working copy that were written during this session: they count as changed even when the file kept its size. */
  writtenUnits?: ReadonlySet<string>
  /** How long a listing of the working copy is reused, in milliseconds; 15 seconds when absent. */
  changedTtlMs?: number
  /** Test totals read off commands this session, by module path, for modules that left no report file. */
  observed?: ReadonlyMap<string, TestTotals>
}

const newest = (...times: (number | null)[]): number | null => {
  const known = times.filter((time): time is number => time !== null)

  return known.length === 0 ? null : Math.max(...known)
}

/** The files of an uplift's working copy and their sizes, reused for a short while so an idle pane does not walk the tree again and again. */
async function workingSizesOf(
  fs: ReaderFs,
  cache: ReaderCache,
  root: string,
  nowMs: number,
  ttlMs: number,
): Promise<Map<string, number> | null> {
  const key = `changed:${root}`
  const hit = cache.get(key)

  if (hit !== undefined && nowMs - hit.mtimeMs < ttlMs) {
    return hit.value as Map<string, number> | null
  }

  const value = await sourceSizes(fs, root)

  cache.set(key, { mtimeMs: nowMs, value })

  return value
}

/** The estate to draw: the map's modules, or what the legacy tree holds. Read once per system, then kept. */
async function estateOf(
  fs: ReaderFs,
  cache: ReaderCache,
  track: TrackKey,
  topology: Topology | null,
  legacyRoot: string,
  system: string,
): Promise<EstateModel | null> {
  if (topology !== null && track !== 'uplift') {
    return estateOfTopology(topology, 0)
  }

  const key = `estate:${legacyRoot}`
  const at = (await mtimeOrNull(fs, legacyRoot)) ?? 0
  const hit = cache.get(key)

  if (hit !== undefined && hit.mtimeMs === at) {
    return hit.value as EstateModel | null
  }

  const found = await discoverEstate(fs, legacyRoot, system)

  cache.set(key, { mtimeMs: at, value: found })

  return found ?? (topology !== null ? estateOfTopology(topology, 0) : null)
}

/** Reads one system's state. Null when the workspace holds no system. */
export async function readSnapshot(
  fs: ReaderFs,
  cache: ReaderCache,
  options: ReadOptions,
): Promise<Snapshot | null> {
  const legacyDir = options.legacyDir ?? 'legacy'
  const systems = await systemsOf(fs, legacyDir)

  const system =
    options.system !== undefined && systems.includes(options.system)
      ? options.system
      : systems[0]

  if (system === undefined) {
    return null
  }

  const dir = join('analysis', system)
  const legacyRoot = join(legacyDir, system)
  const transformRoot = join('modernized', system)
  const upliftRoot = join('modernized', `${system}-uplifted`)
  const reimagineRoot = join('modernized', `${system}-reimagined`)
  const observed = options.observed ?? new Map<string, TestTotals>()

  const [topo, rules, catalog, baseline, reviewsRaw, findingsHead, marks] = await Promise.all([
    cached(fs, cache, join(dir, STAGE_FILES.map), parseTopology),
    cached(fs, cache, join(dir, STAGE_FILES.rules), parseRules),
    cached(fs, cache, join(dir, STAGE_FILES.deltas), parseCatalog),
    cached(fs, cache, join(dir, STAGE_FILES.baseline), parseBaseline),
    readOrNull(fs, join(dir, REVIEWS_FILE)),
    readOrNull(fs, join(dir, STAGE_FILES.harden)),
    Promise.all(
      [
        mtimeOrNull(fs, dir),
        mtimeOrNull(fs, join(dir, STAGE_FILES.preflight)),
        mtimeOrNull(fs, join(dir, STAGE_FILES.assess)),
        mtimeOrNull(fs, join(dir, STAGE_FILES.pilot)),
        mtimeOrNull(fs, join(upliftRoot, 'UPLIFT_NOTES.md')),
        mtimeOrNull(fs, upliftRoot),
        mtimeOrNull(fs, join(dir, STAGE_FILES.spec)),
        mtimeOrNull(fs, join(dir, STAGE_FILES.design)),
        mtimeOrNull(fs, reimagineRoot),
        mtimeOrNull(fs, transformRoot),
      ],
    ),
  ])

  const [analysisAt, preflightAt, assessAt, playbookAt, upliftNotesAt, upliftCopyAt, specAt, designAt, reimagineDirAt, transformDirAt] = marks

  const topology = topo.value
  const moduleIds = topology?.modules.map(node => node.id) ?? []

  const brief = await cached(fs, cache, join(dir, STAGE_FILES.brief), text =>
    parseBrief(text, moduleIds),
  )

  // A brief parsed before the map existed named no modules: parse it again.
  if (
    brief.value !== null &&
    moduleIds.length > 0 &&
    brief.value.phases.length > 0 &&
    brief.value.phases.every(phase => phase.modules.length === 0)
  ) {
    const text = await readOrNull(fs, join(dir, STAGE_FILES.brief))

    if (text !== null) {
      brief.value = parseBrief(text, moduleIds)
      cache.set(join(dir, STAGE_FILES.brief), { mtimeMs: brief.mtimeMs ?? 0, value: brief.value })
    }
  }

  let reviews: ReviewLedger = {}

  if (reviewsRaw !== null) {
    try {
      const parsed = JSON.parse(reviewsRaw) as { reviews?: ReviewLedger }

      reviews = parsed.reviews ?? {}
    } catch {
      reviews = {}
    }
  }

  const isScan = findingsHead !== null && /generated-by:\s*modernize-harden/.test(findingsHead.split('\n')[0] ?? '')

  const transformed = await readModernizedIn(fs, transformRoot, observed)

  const track = pickTrack(options.track ?? 'auto', {
    transformAt: newest(transformDirAt, ...transformed.map(module => module.mtimeMs)),
    // A baseline says nothing of the track: a rewrite records one too, for the legacy behavior it must keep.
    upliftAt: newest(catalog.mtimeMs, playbookAt, upliftNotesAt, upliftCopyAt),
    reimagineAt: newest(specAt, designAt, reimagineDirAt),
  })

  const estate = await estateOf(fs, cache, track, topology, legacyRoot, system)

  let modules: ModernizedModule[] = []
  const byNode = new Map<string, ModernizedModule>()
  const extras: ModernizedModule[] = []
  let uplift: UpliftFacts | null = null

  if (track === 'uplift') {
    const hasCopy = upliftCopyAt !== null
    const legacySizes = estate?.isPartial === false ? estate.fileSizes : undefined
    const workingSizes = hasCopy && legacySizes !== undefined ? await workingSizesOf(fs, cache, upliftRoot, options.nowMs, options.changedTtlMs ?? 15_000) : null
    const changedPaths = legacySizes !== undefined && workingSizes !== null ? changedPathsOf(legacySizes, workingSizes) : null
    const changed = estate !== null && changedPaths !== null ? changedUnitsOf(estate, changedPaths) : new Set<string>()

    for (const id of options.writtenUnits ?? []) {
      changed.add(id)
    }

    const pairs =
      estate !== null && hasCopy
        ? await readUpliftUnits(fs, upliftRoot, estate, changed, baseline.value, observed)
        : []

    modules = pairs.map(pair => pair.module)

    for (const pair of pairs) {
      byNode.set(pair.unit.id, pair.module)
    }

    uplift = {
      catalog: catalog.value,
      baseline: baseline.value,
      hasPlaybook: playbookAt !== null,
      hasNotes: upliftNotesAt !== null,
      hasCopy,
      isChangeKnown: changedPaths !== null,
    }
  } else {
    modules = track === 'reimagine' ? await readModernizedIn(fs, reimagineRoot, observed) : transformed

    if (track === 'transform') {
      const byKey = new Map<string, EstateUnit>()

      for (const unit of estate?.units ?? []) {
        for (const key of keysOfUnit(unit)) {
          byKey.set(keyOf(key), unit)
        }
      }

      for (const module of modules) {
        const unit = byKey.get(keyOf(module.dir))

        if (unit !== undefined) {
          byNode.set(unit.id, module)
        } else {
          extras.push(module)
        }
      }
    } else {
      extras.push(...modules)
    }
  }

  const snapshotFacts = { track, uplift }
  const done = modules.filter(module => isUnitDone(snapshotFacts, module))

  const green = modules.filter(
    module => module.state === 'tests-green' || module.state === 'reviewed' || isUnitDone(snapshotFacts, module),
  )

  const passing = green.reduce(
    (sum, module) => sum + Math.max(0, (module.tests?.tests ?? 0) - (module.tests?.failures ?? 0) - (module.tests?.errors ?? 0)),
    0,
  )

  const withFindings: Stage[] =
    findingsHead !== null || track === 'transform'
      ? [
          {
            key: 'harden',
            label: STAGE_LABELS.harden,
            // Any findings file counts. A harden marker on its first line says the command wrote it, and older or
            // newer versions of the command may or may not stamp one, so its absence is not a reason to doubt the file.
            isDone: findingsHead !== null,
            mtimeMs: null,
          },
        ]
      : []

  const stages: Stage[] = [
    ...(track === 'transform'
      ? [
          { key: 'preflight' as const, label: STAGE_LABELS.preflight, isDone: preflightAt !== null, mtimeMs: preflightAt },
          { key: 'assess' as const, label: STAGE_LABELS.assess, isDone: assessAt !== null, mtimeMs: assessAt },
          {
            key: 'map' as const,
            label: STAGE_LABELS.map,
            isDone: topology !== null,
            mtimeMs: topo.mtimeMs,
            ...(topology !== null && { detail: `${topology.modules.length} modules` }),
          },
          {
            key: 'rules' as const,
            label: STAGE_LABELS.rules,
            isDone: rules.value !== null && rules.value.rules.length > 0,
            mtimeMs: rules.mtimeMs,
            ...(rules.value !== null && { detail: `${rules.value.rules.length} rules` }),
          },
          {
            key: 'brief' as const,
            label: STAGE_LABELS.brief,
            isDone: brief.value !== null,
            mtimeMs: brief.mtimeMs,
            ...(brief.value !== null && {
              detail: brief.value.approval.isSigned ? 'approved' : 'unapproved',
            }),
          },
          {
            // Transform writes under modernized/, not analysis/: this stage is done once a module's tests are green.
            key: 'transform' as const,
            label: STAGE_LABELS.transform,
            isDone: green.length > 0,
            mtimeMs: null,
            ...(modules.length > 0 && {
              detail: green.length === 0 ? 'in progress' : passing > 0 ? `${passing} green` : `${green.length} module${green.length === 1 ? '' : 's'}`,
            }),
          },
        ]
      : track === 'uplift'
        ? [
            { key: 'preflight' as const, label: STAGE_LABELS.preflight, isDone: preflightAt !== null, mtimeMs: preflightAt },
            {
              key: 'deltas' as const,
              label: STAGE_LABELS.deltas,
              isDone: catalog.mtimeMs !== null,
              mtimeMs: catalog.mtimeMs,
              ...(catalog.value !== null && { detail: `${catalog.value.count} deltas` }),
            },
            {
              key: 'baseline' as const,
              label: STAGE_LABELS.baseline,
              isDone: baseline.mtimeMs !== null,
              mtimeMs: baseline.mtimeMs,
              ...(baseline.value !== null && {
                detail: baseline.value.isTargetOnly
                  ? 'target-only'
                  : baseline.value.results !== null
                    ? `${baseline.value.results.toLocaleString('en-US')} tests`
                    : undefined,
              }),
            },
            { key: 'pilot' as const, label: STAGE_LABELS.pilot, isDone: playbookAt !== null, mtimeMs: playbookAt },
            {
              key: 'migrate' as const,
              label: STAGE_LABELS.migrate,
              isDone: modules.length > 0 && playbookAt !== null,
              mtimeMs: null,
              ...(modules.length > 0 && { detail: `${modules.length} module${modules.length === 1 ? '' : 's'}` }),
            },
            {
              key: 'verify' as const,
              label: STAGE_LABELS.verify,
              isDone: upliftNotesAt !== null,
              mtimeMs: upliftNotesAt,
              ...(modules.length > 0 && { detail: `${done.length}/${modules.length} match` }),
            },
          ]
        : [
            { key: 'preflight' as const, label: STAGE_LABELS.preflight, isDone: preflightAt !== null, mtimeMs: preflightAt },
            { key: 'spec' as const, label: STAGE_LABELS.spec, isDone: specAt !== null, mtimeMs: specAt },
            { key: 'design' as const, label: STAGE_LABELS.design, isDone: designAt !== null, mtimeMs: designAt },
            {
              key: 'scaffold' as const,
              label: STAGE_LABELS.scaffold,
              isDone: modules.length > 0,
              mtimeMs: null,
              ...(modules.length > 0 && { detail: `${modules.length} service${modules.length === 1 ? '' : 's'}` }),
            },
            {
              key: 'tests' as const,
              label: STAGE_LABELS.tests,
              isDone: modules.length > 0 && green.length === modules.length,
              mtimeMs: null,
              ...(modules.length > 0 && { detail: `${green.length}/${modules.length} green` }),
            },
          ]),
    ...withFindings,
  ]

  const loc = (estate?.units ?? []).reduce((sum, unit) => sum + Math.max(1, unit.size), 0)

  const locDone = (estate?.units ?? []).reduce((sum, unit) => {
    const module = byNode.get(unit.id)

    return module !== undefined && isUnitDone(snapshotFacts, module) ? sum + Math.max(1, unit.size) : sum
  }, 0)

  const attention: string[] = []

  for (const module of modules) {
    const row = track === 'uplift' ? (baseline.value?.rows.get(module.dir.toLowerCase()) ?? null) : null

    if (module.state === 'tests-red' && module.tests !== null) {
      const bad = module.tests.failures + module.tests.errors

      attention.push(
        track === 'uplift'
          ? `${module.dir}: ${bad} failing, the baseline had ${row === null ? 0 : row.fail + row.error}`
          : `${module.dir}: ${bad} of ${module.tests.tests} tests red`,
      )
    }

    if (module.tests !== null && module.tests.reports > 0 && module.tests.tests === 0) {
      attention.push(`${module.dir}: test reports exist but 0 cases executed`)
    }

    if (track === 'transform' && module.state === 'tests-green' && module.hasNotes && !module.hasReviewSection) {
      attention.push(`${module.dir}: tests green; the notes do not show the architecture review`)
    }
  }

  for (const extra of extras) {
    if (track === 'transform' && extra.hasMain && (!extra.hasNotes || !extra.hasTests)) {
      attention.push(
        `${extra.dir}: shared code without ${[!extra.hasTests && 'tests', !extra.hasNotes && 'notes'].filter(Boolean).join(' or ')}; an unfinished transform`,
      )
    }

    if (track === 'reimagine' && extra.hasMain && !extra.hasTests) {
      attention.push(`${extra.dir}: scaffolded with no acceptance tests`)
    }
  }

  if (track === 'uplift' && uplift !== null) {
    if (uplift.baseline?.isTargetOnly === true) {
      attention.push('the baseline is target-only: the source runtime could not run, so nothing is compared')
    }

    if (modules.length > 0 && !uplift.hasPlaybook) {
      attention.push(`${modules.length} module${modules.length === 1 ? '' : 's'} touched before a playbook was written: pilot one first`)
    }

    if (modules.length > 0 && uplift.baseline === null) {
      attention.push('modules touched before a baseline was recorded: nothing to compare them with')
    }
  }

  if (
    brief.mtimeMs !== null &&
    rules.mtimeMs !== null &&
    brief.mtimeMs < rules.mtimeMs
  ) {
    attention.push('the brief is older than the rule set it was planned from')
  }

  if (rules.value !== null) {
    const pending = rules.value.rules.filter(
      rule => rule.priority === 'P0' && needsReview(rule) && reviews[rule.id] === undefined,
    ).length

    const wrong = Object.values(reviews).filter(entry => entry.verdict === 'wrong').length

    if (wrong > 0) {
      attention.push(`${wrong} rule${wrong === 1 ? '' : 's'} marked wrong by a reviewer`)
    }

    if (pending > 0) {
      attention.push(`${pending} P0 rule${pending === 1 ? '' : 's'} flagged for a person and not reviewed yet`)
    }
  }

  const next: NextStep | null =
    track === 'uplift'
      ? nextOfUplift(options.commandPrefix, system, stages)
      : track === 'reimagine'
        ? nextOfReimagine(options.commandPrefix, system, stages)
        : nextOfTransform(options.commandPrefix, system, stages, brief.value, byNode)

  return {
    system,
    systems,
    track,
    hasAnalysis: analysisAt !== null,
    stages,
    estate,
    topology,
    rules: rules.value,
    brief: brief.value,
    modules,
    byNode,
    extras,
    uplift,
    findings: { exists: findingsHead !== null, isScan },
    reviews,
    percent: track === 'reimagine' || loc === 0 ? null : locDone / loc,
    totals: {
      modules: estate?.units.length ?? 0,
      done: [...byNode.values()].filter(module => isUnitDone(snapshotFacts, module)).length,
      loc,
      locDone,
    },
    attention,
    next,
    readAtMs: options.nowMs,
  }
}

/** One line for the status bar and the prompt's hidden context. */
export function oneLineOf(snapshot: Snapshot): string {
  const countable = snapshot.stages.filter(stage => stage.key !== 'harden' && stage.key !== 'transform')
  const done = countable.filter(stage => stage.isDone).length

  const parts =
    snapshot.track === 'transform'
      ? [`${snapshot.system}: discovery ${done}/5`]
      : [`${snapshot.system}: ${TRACK_LABELS[snapshot.track]} ${done}/${countable.length} steps`]

  if (snapshot.brief !== null) {
    parts.push(snapshot.brief.approval.isSigned ? 'brief approved' : 'brief awaiting approval')
  }

  if (snapshot.totals.modules > 0 && snapshot.modules.length > 0) {
    parts.push(
      snapshot.track === 'reimagine'
        ? `${snapshot.modules.length} services scaffolded`
        : `${snapshot.totals.done}/${snapshot.totals.modules} modules ${snapshot.track === 'uplift' ? 'match the baseline' : 'reviewed'}`,
    )
  }

  if (snapshot.attention.length > 0) {
    parts.push(`${snapshot.attention.length} need attention`)
  }

  return parts.join(' · ')
}
