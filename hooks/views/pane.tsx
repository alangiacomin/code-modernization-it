/* @jsxRuntime classic */
/* @jsx h */
/* @jsxFrag Fragment */
import type { Elements, RenderChildren, RenderElement } from 'claude-code'

import { lineOf, tallyOf } from '../fleet/fleet'
import { countsOf, hexOf, STATE_COLORS, stateWord, type Tile } from '../map/estate'
import { isUnitDone, type Snapshot } from '../reader/progress'
import { TRACK_LABELS, TRACK_UNITS } from '../reader/tracks'
import { RASTER_KEY, type State } from '../state'

/** The elements a pane draws with; `Raster` only where the surface has it (the terminal). */
export type Kit = Pick<Elements['terminal'], 'Box' | 'Text' | 'Button'> &
  Partial<Pick<Elements['terminal'], 'Raster' | 'Code' | 'Input' | 'Select'>>

export type PaneActions = {
  /** Follow the workspace's next system, when it holds more than one. */
  system: () => void
  next: () => void
  refresh: () => void
  review: () => void
  sign: () => void
  close: () => void
  stop: () => void
}

export type PaneFrame = {
  columns: number
  rows: number
  placement: 'dock' | 'inline'
  nowMs: number
  /** The packed cells for the estate, when there is room and a map to draw. */
  estate: { cells: string; columns: number; rows: number; tiles: Tile[] } | null
  plan: PanePlan
}

const pad = (text: string, width: number) =>
  text.length >= width ? text.slice(0, Math.max(0, width)) : text + ' '.repeat(width - text.length)

const clip = (text: string, width: number) =>
  text.length <= width ? text : `${text.slice(0, Math.max(0, width - 1))}…`

const ago = (ms: number): string => {
  const s = Math.max(0, Math.round(ms / 1000))

  return s < 60 ? `${s}s` : s < 3600 ? `${Math.floor(s / 60)}m${String(s % 60).padStart(2, '0')}s` : `${Math.floor(s / 3600)}h${String(Math.floor((s % 3600) / 60)).padStart(2, '0')}m`
}

const barOf = (fraction: number, width: number): { full: string; rest: string } => {
  const filled = Math.max(0, Math.min(width, Math.round(fraction * width)))

  return { full: '━'.repeat(filled), rest: '─'.repeat(width - filled) }
}

function rule(kit: Kit, title: string, width: number, right = ''): RenderChildren {
  const { Box, Text } = kit
  const fill = Math.max(1, width - title.length - right.length - 2)

  return (
    <Box>
      <Text bold color="cyan">{title}</Text>
      <Text dimColor>{` ${'─'.repeat(fill)} `}</Text>
      <Text color="yellow">{right}</Text>
    </Box>
  )
}

/** The rows the stage rail takes when it wraps at `width`. */
const railRowsOf = (snapshot: Snapshot, width: number): number =>
  Math.max(1, Math.ceil(snapshot.stages.reduce((sum, stage) => sum + stage.label.length + 3, 0) / Math.max(10, width)))

/** What the estate is made of, in one dim line: its languages, and how many units it was read into. */
function estateLine(snapshot: Snapshot): string {
  const estate = snapshot.estate

  if (estate === null) {
    return ''
  }

  const languages = estate.languages
    .filter(entry => entry.share >= 0.03)
    .map(entry => `${entry.name} ${Math.round(entry.share * 100)}%`)
    .join(' · ')

  const noun = estate.granularity === 'build module' ? 'build module' : estate.granularity === 'module' ? 'module' : estate.granularity
  const count = `${estate.units.length.toLocaleString('en-US')} ${noun}${estate.units.length === 1 ? '' : 's'}`
  const from = estate.source === 'map' ? '' : ' (read off the tree)'

  return `${languages === '' ? '' : `${languages} · `}${count}${estate.isPartial ? '+' : ''}${from}`
}

/** The rows the header takes: the title, the stage rail, the estate line and the progress bar. */
export const headerRowsOf = (snapshot: Snapshot | null, width: number): number =>
  snapshot === null
    ? 3
    : 1 + railRowsOf(snapshot, width) + (estateLine(snapshot) === '' ? 0 : 1) + (snapshot.percent !== null ? 1 : 0)

function header(kit: Kit, snapshot: Snapshot, width: number, actions: PaneActions): RenderChildren {
  const { Box, Text, Button } = kit
  const target = snapshot.brief?.target
  const percent = snapshot.percent
  const measure = snapshot.estate?.measure === 'bytes' ? 'size' : 'loc'
  const right = percent === null ? '' : `${(percent * 100).toFixed(percent < 0.1 ? 1 : 0)}% by ${measure}`
  const left = `${snapshot.system}${target !== undefined ? ` → ${target}` : ''}`
  const bar = barOf(percent ?? 0, Math.max(4, width - right.length - 1))
  const summary = estateLine(snapshot)
  const at = snapshot.systems.indexOf(snapshot.system)
  const many = snapshot.systems.length > 1

  return (
    <Box flexDirection="column">
      <Box justifyContent="space-between">
        <Text bold wrap="truncate-end">{clip(`${left} · ${TRACK_LABELS[snapshot.track]}`, Math.max(8, width - (many ? 22 : 9)))}</Text>
        <Box columnGap={1}>
          {many ? <Button key="system" dimColor onPress={actions.system}>{`system ${at + 1}/${snapshot.systems.length}`}</Button> : null}
          <Button key="hide" dimColor onPress={actions.close}>hide</Button>
        </Box>
      </Box>
      <Box flexWrap="wrap">
        {snapshot.stages.map(stage => (
          <Text color={stage.isDone ? 'green' : undefined} dimColor={!stage.isDone}>
            {`${stage.isDone ? '✓' : '·'} ${stage.label} `}
          </Text>
        ))}
      </Box>
      {summary !== '' ? <Text dimColor wrap="truncate-end">{clip(summary, width)}</Text> : null}
      {percent !== null ? (
        <Box>
          <Text color="green">{bar.full}</Text>
          <Text dimColor>{bar.rest}</Text>
          <Text>{` ${right}`}</Text>
        </Box>
      ) : null}
    </Box>
  )
}

function estate(kit: Kit, snapshot: Snapshot, frame: PaneFrame, width: number): RenderChildren {
  const { Box, Text, Raster } = kit

  if (frame.estate === null || Raster === undefined) {
    return null
  }

  const counts = countsOf(frame.estate.tiles)

  return (
    <Box flexDirection="column">
      <Raster
        key={RASTER_KEY}
        columns={frame.estate.columns}
        rows={frame.estate.rows}
        cells={frame.estate.cells}
      />
      <Box flexWrap="wrap" width={width}>
        {counts.map(entry => (
          <Text>
            <Text color={hexOf(STATE_COLORS[entry.state])}>■</Text>
            <Text dimColor>{` ${stateWord(snapshot.track, entry.state)} ${entry.count}  `}</Text>
          </Text>
        ))}
      </Box>
    </Box>
  )
}

function phases(kit: Kit, snapshot: Snapshot, width: number, max: number): RenderChildren {
  const { Box, Text } = kit
  const brief = snapshot.brief

  if (brief === null || brief.phases.length === 0) {
    return null
  }

  const isDone = (ids: readonly string[]) =>
    ids.length > 0 &&
    ids.every(id => {
      const module = snapshot.byNode.get(id)

      return module !== undefined && isUnitDone(snapshot, module)
    })

  const ordered = [...brief.phases].sort((a, b) => a.number - b.number)
  const currentIndex = Math.max(0, ordered.findIndex(phase => !isDone(phase.modules)))
  const start = Math.max(0, Math.min(currentIndex - 1, ordered.length - max))
  const shown = ordered.slice(start, start + max)
  const doneCount = ordered.filter(phase => isDone(phase.modules)).length

  return (
    <Box flexDirection="column">
      {rule(kit, 'Phases', width, `${doneCount}/${ordered.length}`)}
      {shown.map(phase => {
        const done = isDone(phase.modules)
        const isCurrent = ordered[currentIndex] === phase && !done
        const ticked = phase.criteria.filter(criterion => criterion.isTicked).length
        const right = `${phase.criteria.length > 0 ? `${ticked}/${phase.criteria.length} ☑ ` : ''}${pad(phase.size ?? '', 2)}`
        const label = `${done ? '✓' : isCurrent ? '▸' : '·'} P${phase.number} ${phase.title}`

        return (
          <Box>
            <Text
              color={done ? 'green' : isCurrent ? 'cyan' : undefined}
              bold={isCurrent}
              dimColor={!done && !isCurrent}
            >
              {pad(clip(label, width - right.length - 1), width - right.length - 1)}
            </Text>
            <Text dimColor>{` ${right}`}</Text>
          </Box>
        )
      })}
      {ordered.length > shown.length ? (
        <Text dimColor>{`  … ${ordered.length - shown.length} more phases`}</Text>
      ) : null}
    </Box>
  )
}

/** Units of work in the order that helps most: problems first in an uplift, the newest first in a rewrite. */
function orderOf(snapshot: Snapshot): Snapshot['modules'] {
  if (snapshot.track !== 'uplift') {
    return [...snapshot.modules].sort((a, b) => b.mtimeMs - a.mtimeMs)
  }

  const rank = (state: string) => (state === 'tests-red' ? 0 : state === 'scaffolded' ? 1 : state === 'tests-green' ? 2 : 3)

  return [...snapshot.modules].sort((a, b) => rank(a.state) - rank(b.state) || (b.tests?.tests ?? 0) - (a.tests?.tests ?? 0))
}

function modules(kit: Kit, snapshot: Snapshot, width: number, max: number): RenderChildren {
  const { Box, Text } = kit
  const all = orderOf(snapshot)

  if (all.length === 0) {
    return null
  }

  return (
    <Box flexDirection="column">
      {rule(kit, TRACK_UNITS[snapshot.track].many, width, snapshot.track === 'reimagine' ? String(all.length) : `${snapshot.totals.done}/${snapshot.totals.modules}`)}
      {all.slice(0, max).map(module => {
        const tests = module.tests
        const bad = tests === null ? 0 : tests.failures + tests.errors
        const isWorse = module.state === 'tests-red'

        // In an uplift a module may fail what the baseline already failed: red is only for what got worse.
        const testText =
          tests === null
            ? ''
            : isWorse
              ? snapshot.track === 'uplift'
                ? `${bad} failing`
                : `${bad}/${tests.tests} red`
              : bad > 0 && snapshot.track !== 'uplift'
                ? `${bad}/${tests.tests} red`
                : `${tests.tests} ${snapshot.track === 'uplift' ? 'tests' : 'green'}`

        const color = hexOf(STATE_COLORS[module.state])
        const word = stateWord(snapshot.track, module.state)
        const name = clip(module.dir, Math.max(8, width - word.length - testText.length - 5))

        return (
          <Box>
            <Text color={color}>■ </Text>
            <Text bold>{name}</Text>
            <Text dimColor>{`  ${word}`}</Text>
            <Text color={isWorse || (bad > 0 && snapshot.track !== 'uplift') ? 'red' : 'green'}>
              {testText === '' ? '' : `  ${testText}`}
            </Text>
          </Box>
        )
      })}
      {all.length > max ? <Text dimColor>{`  … ${all.length - max} more`}</Text> : null}
    </Box>
  )
}

function session(kit: Kit, state: State, frame: PaneFrame, width: number, max: number): RenderChildren {
  const { Box, Text } = kit
  const activity = state.activity
  const fleet = tallyOf(state.fleet, frame.nowMs)

  // A workflow's agents run on while the main loop waits between turns: that is not idle.
  const status = activity.isWorking
    ? `● working ${ago(frame.nowMs - activity.turnStartMs)}`
    : fleet.active > 0
      ? `● ${fleet.active} agents working`
      : '○ idle'

  const running = [...activity.running.values()]
    .filter(call => call.agentId === undefined)
    .sort((a, b) => a.startMs - b.startMs)

  const share = activity.toolMs > 0 ? Math.round((activity.testMs / activity.toolMs) * 100) : 0

  // Rows in the order they matter; the block draws as many as it was given.
  const rows: RenderChildren[] = []

  if (activity.step !== null) {
    rows.push(<Text color="cyan" wrap="truncate-end">{clip(`  ${activity.step}`, width)}</Text>)
  }

  if (fleet.total > 0) {
    rows.push(
      <Text wrap="truncate-end">
        <Text color="cyan">{'  ⛭ '}</Text>
        <Text>{`${fleet.active} agents active`}</Text>
        <Text dimColor>{` · ${fleet.done}/${fleet.total} done · ${fleet.calls} calls${fleet.errors > 0 ? ` · ${fleet.errors} errors` : ''}${fleet.stalled > 0 ? ` · ${fleet.stalled} quiet` : ''}`}</Text>
      </Text>,
    )
  }

  for (const call of running.slice(-2)) {
    rows.push(
      <Box>
        <Text color="yellow">{'  ◌ '}</Text>
        <Text>{pad(clip(`${call.tool} ${call.subject}`, width - 10), width - 10)}</Text>
        <Text dimColor>{` ${ago(frame.nowMs - call.startMs)}`}</Text>
      </Box>,
    )
  }

  const summary = [
    activity.xrays > 0 ? `x-ray notes ${activity.xrays}` : '',
    activity.testRuns > 0 ? `tests ${share}% of tool time (${activity.testRuns} runs)` : '',
  ].filter(part => part !== '')

  const tail: RenderChildren[] = summary.length > 0 ? [<Text dimColor wrap="truncate-end">{clip(`  ${summary.join(' · ')}`, width)}</Text>] : []
  const room = Math.max(0, max - rows.length - tail.length)
  const agents = fleet.recent.slice(0, Math.min(3, Math.floor(room / 2)))

  for (const row of agents) {
    rows.push(
      <Text dimColor wrap="truncate-end">
        {clip(`     ${row.unit !== undefined ? `${row.unit} ` : ''}${row.lastTool} ${row.lastSubject}`, width)}
      </Text>,
    )
  }

  for (const call of activity.finished.slice(-Math.max(0, max - rows.length - tail.length))) {
    rows.push(
      <Box>
        <Text color={call.isOk ? 'green' : 'red'}>{call.isOk ? '  ✓ ' : '  ✗ '}</Text>
        <Text dimColor wrap="truncate-end">{clip(`${call.tool} ${call.subject}${call.note !== undefined ? ` · ${call.note}` : ''}`, width - 4)}</Text>
      </Box>,
    )
  }

  return (
    <Box flexDirection="column">
      {rule(kit, 'Session', width, status)}
      {[...rows.slice(0, Math.max(0, max - tail.length)), ...tail]}
    </Box>
  )
}

function attention(kit: Kit, state: State, snapshot: Snapshot, width: number, max: number): RenderChildren {
  const { Box, Text } = kit
  const shared = tallyOf(state.fleet, 0).shared.map(signature => lineOf(signature, 'short'))

  const lines = [...shared, ...snapshot.attention]

  if (lines.length === 0) {
    return null
  }

  return (
    <Box flexDirection="column">
      {rule(kit, 'Attention', width, String(lines.length))}
      {lines.slice(0, max).map(line => (
        <Text color="yellow" wrap="truncate-end">{clip(`  ! ${line}`, width)}</Text>
      ))}
      {lines.length > max ? <Text dimColor>{`  … ${lines.length - max} more`}</Text> : null}
    </Box>
  )
}

function nextBlock(
  kit: Kit,
  snapshot: Snapshot,
  actions: PaneActions,
  state: State,
  width: number,
  hasHint: boolean,
): RenderChildren {
  const { Box, Text, Button } = kit
  const next = snapshot.next
  const hasRules = (snapshot.rules?.rules.length ?? 0) > 0

  return (
    <Box flexDirection="column">
      {rule(kit, 'Next', width)}
      {next !== null ? (
        <Box flexDirection="column" paddingLeft={2}>
          <Text color={next.isByHand ? undefined : 'cyan'} bold={!next.isByHand} wrap="truncate-end">
            {`${next.text}${next.isByHand ? '  (by hand)' : ''}`}
          </Text>
          <Text dimColor wrap="truncate-end">{next.reason}</Text>
        </Box>
      ) : (
        <Text dimColor>{'  nothing to suggest'}</Text>
      )}
      <Box marginTop={1} flexWrap="wrap" columnGap={1}>
        {next !== null && !next.isByHand ? (
          <Button key="next" onPress={actions.next}>next</Button>
        ) : null}
        {hasRules ? <Button key="review" onPress={actions.review}>review rules</Button> : null}
        {state.activity.isWorking && state.fleet.seen > 0 ? (
          <Button key="stop" onPress={actions.stop}>stop the run</Button>
        ) : null}
        <Button key="refresh" dimColor onPress={actions.refresh}>refresh</Button>
      </Box>
      {hasHint ? <Text dimColor>{'click, or ctrl+x tab then tab and enter'}</Text> : null}
    </Box>
  )
}

/** How the pane's rows are shared out, so the whole of it shows without scrolling. */
export type PanePlan = {
  estate: number
  phases: number
  modules: number
  attention: number
  session: number
  /** Blank rows between blocks. */
  gap: 0 | 1
  /** Whether the dim hint under the buttons is drawn. */
  hasHint: boolean
}

/**
 * Shares `rows` body rows between the blocks. Fixed costs first (header,
 * legend, the Next block, each list's title), then the lists at their
 * minimum, then what is left goes to the map and the phase list.
 */
export function planOf(
  rows: number,
  placement: 'dock' | 'inline',
  counts: { phases: number; modules: number; attention: number; hasMap: boolean; headerRows: number },
): PanePlan {
  if (placement === 'inline') {
    return {
      estate: counts.hasMap ? Math.max(4, Math.min(6, rows - 6 - counts.headerRows)) : 0,
      phases: 0,
      modules: Math.min(1, counts.modules),
      attention: Math.min(1, counts.attention),
      session: 1,
      gap: 0,
      hasHint: false,
    }
  }

  const gap: 0 | 1 = rows >= 52 ? 1 : 0
  const hasHint = rows >= 44
  const attention = Math.min(counts.attention, rows >= 40 ? 3 : 2)
  const modules = Math.min(counts.modules, rows >= 48 ? 3 : rows >= 38 ? 2 : 1)
  const sessionMin = rows >= 40 ? 4 : 3

  // header · legend 1 · next: title, command, reason, blank, buttons (+hint)
  const fixed =
    counts.headerRows +
    (counts.hasMap ? 1 : 0) +
    (5 + (hasHint ? 1 : 0)) +
    (attention > 0 ? 1 + attention : 0) +
    (modules > 0 ? 1 + modules : 0) +
    (1 + sessionMin) +
    (counts.phases > 0 ? 1 : 0)

  const blocks = 3 + (counts.hasMap ? 1 : 0) + (attention > 0 ? 1 : 0) + (modules > 0 ? 1 : 0) + (counts.phases > 0 ? 1 : 0)
  const spare = Math.max(0, rows - fixed - gap * (blocks - 1))
  const phases = counts.phases > 0 ? Math.max(1, Math.min(counts.phases, Math.floor(spare * 0.3))) : 0
  const estate = counts.hasMap ? Math.max(4, Math.min(16, spare - phases - (counts.phases > phases ? 1 : 0))) : 0
  const left = Math.max(0, spare - phases - estate - (counts.phases > phases ? 1 : 0))

  const plan: PanePlan = { estate, phases, modules, attention, session: sessionMin + Math.min(4, left), gap, hasHint }

  // A body too short for even the minimums sheds rows in the order they matter least.
  const totalOf = (p: PanePlan) =>
    counts.headerRows +
    (p.estate > 0 ? p.estate + 1 : 0) +
    (p.phases > 0 ? 1 + p.phases + (counts.phases > p.phases ? 1 : 0) : 0) +
    (p.modules > 0 ? 1 + p.modules + (counts.modules > p.modules ? 1 : 0) : 0) +
    (5 + (p.hasHint ? 1 : 0)) +
    (p.attention > 0 ? 1 + p.attention + (counts.attention > p.attention ? 1 : 0) : 0) +
    (1 + p.session)

  const shed: (() => boolean)[] = [
    () => (plan.hasHint ? ((plan.hasHint = false), true) : false),
    () => (plan.estate > 4 ? ((plan.estate -= 1), true) : false),
    () => (plan.phases > 1 ? ((plan.phases -= 1), true) : false),
    () => (plan.session > 2 ? ((plan.session -= 1), true) : false),
    () => (plan.attention > 1 ? ((plan.attention -= 1), true) : false),
    () => (plan.modules > 0 ? ((plan.modules = 0), true) : false),
    () => (plan.phases > 0 ? ((plan.phases = 0), true) : false),
    () => (plan.estate > 0 ? ((plan.estate = 0), true) : false),
    () => (plan.attention > 0 ? ((plan.attention = 0), true) : false),
    () => (plan.session > 1 ? ((plan.session -= 1), true) : false),
  ]

  for (let guard = 0; guard < 80 && totalOf(plan) > rows; guard += 1) {
    if (!shed.some(step => step())) {
      break
    }
  }

  return plan
}

/** The pane's body. */
export function paneView(
  kit: Kit,
  state: State,
  frame: PaneFrame,
  actions: PaneActions,
): RenderElement {
  const { Box, Text } = kit
  const width = Math.max(20, frame.columns)
  const snapshot = state.snapshot

  if (snapshot === null) {
    return (
      <Box flexDirection="column" paddingRight={1}>
        <Text bold>modernization</Text>
        <Text dimColor wrap="wrap">
          {state.readError !== null
            ? `could not read the workspace: ${state.readError}`
            : 'no system found under legacy/ or analysis/ yet. Put the system under legacy/<name>/ and run the preflight command to begin.'}
        </Text>
      </Box>
    )
  }

  const plan = frame.plan

  return (
    <Box flexDirection="column" paddingRight={1} rowGap={plan.gap}>
      {header(kit, snapshot, width, actions)}
      {estate(kit, snapshot, frame, width)}
      {plan.phases > 0 ? phases(kit, snapshot, width, plan.phases) : null}
      {plan.modules > 0 ? modules(kit, snapshot, width, plan.modules) : null}
      {nextBlock(kit, snapshot, actions, state, width, plan.hasHint)}
      {plan.attention > 0 ? attention(kit, state, snapshot, width, plan.attention) : null}
      {session(kit, state, frame, width, plan.session)}
    </Box>
  )
}

/**
 * The one row that stands where the pane was while it is hidden: what the workspace says in a line, and the
 * button that brings the pane back. It is drawn in the band above the prompt, which the person can collapse.
 */
export function showBar(
  kit: Pick<Kit, 'Box' | 'Text' | 'Button'>,
  line: string,
  width: number,
  onShow: () => void,
): RenderElement {
  const { Box, Text, Button } = kit

  return (
    // The band draws its own `[-]` collapse control at its right edge: leave it room.
    <Box justifyContent="space-between" paddingRight={5}>
      <Text dimColor wrap="truncate-end">{clip(line, Math.max(8, width - 24))}</Text>
      <Button key="show-pane" hotkey="m" onPress={onShow}>show pane</Button>
    </Box>
  )
}
