import { estateOfTopology, type EstateUnit } from '../reader/estate-model'
import type { ModuleState } from '../reader/modernized'
import type { Snapshot } from '../reader/progress'
import { STATE_WORDS_BY_TRACK, type TrackKey } from '../reader/tracks'
import { DEFAULT_COLOR, luma, mix, packCells, type Cell } from './raster'
import { layoutGroups, type Rect } from './treemap'

/**
 * The estate map: every unit of the legacy system as a tile, sized by its lines of code
 * (or bytes of source, where there is no map), grouped by domain or directory, coloured by
 * how far its modernization has come, and lit for a moment when a file beneath it is read or written.
 */

export type TouchKind = 'read' | 'write'

export type Touch = { atMs: number; kind: TouchKind }

export type TileState = ModuleState | 'untouched'

export type Tile = {
  id: string
  name: string
  domain: string
  loc: number
  state: TileState
  rect: Rect
  isNext: boolean
}

export type Estate = {
  columns: number
  rows: number
  tiles: Tile[]
  /** Base64 for the Raster's `cells`. */
  cells: string
  /** True while any tile is still fading from a touch, so another frame is due. */
  isAnimating: boolean
}

/** How long a touch stays visible, in milliseconds. */
export const FLASH_MS = 4000

export const STATE_COLORS: Record<TileState, number> = {
  untouched: 0x39414f,
  scaffolded: 0x4b5d80,
  'tests-written': 0x94741f,
  'tests-red': 0xb23b3b,
  'tests-green': 0x2c7a4c,
  reviewed: 0x2fa568,
  ported: 0x2b8ea6,
  switched: 0x3bd184,
}

/** What a state is called in a track: the same colors, worded for what the work is. */
export const stateWord = (track: TrackKey, state: TileState): string => STATE_WORDS_BY_TRACK[track][state] ?? state

const FLASH_COLORS: Record<TouchKind, number> = {
  read: 0x9fd4ff,
  write: 0xffe27a,
}

/** A stable small jitter per tile, so neighbours of one state still read as separate tiles. */
const jitterOf = (id: string): number => {
  let hash = 2166136261

  for (let index = 0; index < id.length; index += 1) {
    hash = Math.imul(hash ^ id.charCodeAt(index), 16777619)
  }

  return ((hash >>> 0) % 1000) / 1000
}

/** The module ids of the step the snapshot says comes next, when it is a transform. */
function nextModuleOf(snapshot: Snapshot): string | null {
  const text = snapshot.next?.text ?? ''
  const match = /transform\s+\S+\s+(\S+)/.exec(text)

  return snapshot.next?.isByHand === false ? (match?.[1] ?? null) : null
}

/** Lays the snapshot's estate out in `columns` by `rows` cells. */
export function tilesOf(snapshot: Snapshot, columns: number, rows: number): Tile[] {
  const estate = snapshot.estate ?? (snapshot.topology !== null ? estateOfTopology(snapshot.topology, 0) : null)

  if (estate === null || columns < 4 || rows < 2) {
    return []
  }

  const next = nextModuleOf(snapshot)
  const groups = new Map<string, EstateUnit[]>()

  for (const unit of estate.units) {
    const members = groups.get(unit.group) ?? []

    members.push(unit)
    groups.set(unit.group, members)
  }

  const placed = layoutGroups(
    [...groups.entries()].map(([name, members]) => ({
      name,
      items: members.map(unit => ({ item: unit, size: Math.max(1, unit.size) })),
    })),
    { x: 0, y: 0, w: columns, h: rows },
  )

  return placed.flatMap(group =>
    group.items
      .filter(entry => entry.rect.w > 0 && entry.rect.h > 0)
      .map(entry => ({
        id: entry.item.id,
        name: entry.item.name,
        domain: group.name,
        loc: entry.item.size,
        state: snapshot.byNode.get(entry.item.id)?.state ?? ('untouched' as const),
        rect: entry.rect,
        isNext: entry.item.id === next,
      })),
  )
}

/** Paints the tiles into cells and packs them for the Raster. */
export function paint(
  tiles: readonly Tile[],
  columns: number,
  rows: number,
  touches: ReadonlyMap<string, Touch>,
  nowMs: number,
): Estate {
  const blank: Cell = { glyph: ' ', fg: DEFAULT_COLOR, bg: DEFAULT_COLOR }
  const cells: Cell[] = Array.from({ length: columns * rows }, () => blank)
  let isAnimating = false

  for (const tile of tiles) {
    const base = mix(STATE_COLORS[tile.state], 0xffffff, (jitterOf(tile.id) - 0.5) * 0.14 + 0.02)
    const touch = touches.get(tile.id)
    const age = touch !== undefined ? nowMs - touch.atMs : Infinity
    const heat = age < FLASH_MS ? 1 - age / FLASH_MS : 0

    if (heat > 0) {
      isAnimating = true
    }

    const body = heat > 0 && touch !== undefined ? mix(base, FLASH_COLORS[touch.kind], heat * 0.85) : base
    const edge = mix(body, 0x000000, 0.32)
    const ink = luma(body) > 140 ? 0x101418 : 0xf2f5f8
    const { x, y, w, h } = tile.rect
    const hasBevel = w >= 3 && h >= 2
    const label = w >= 4 ? (tile.isNext ? '▸' : '') + tile.name : w >= 2 && tile.isNext ? '▸' : ''
    const shown = label.slice(0, Math.max(0, w - (hasBevel ? 1 : 0)))

    for (let row = 0; row < h; row += 1) {
      for (let col = 0; col < w; col += 1) {
        const cx = x + col
        const cy = y + row

        if (cx >= columns || cy >= rows) {
          continue
        }

        const isEdge = hasBevel && (col === w - 1 || row === h - 1)
        const glyph = row === 0 && col < shown.length ? (shown[col] ?? ' ') : ' '

        cells[cy * columns + cx] = { glyph, fg: ink, bg: isEdge ? edge : body }
      }
    }
  }

  return { columns, rows, tiles: [...tiles], cells: packCells(cells), isAnimating }
}

/** How many modules sit in each state, in the order the legend draws them. */
export function countsOf(tiles: readonly Tile[]): { state: TileState; count: number }[] {
  const order: TileState[] = [
    'untouched',
    'scaffolded',
    'tests-written',
    'tests-red',
    'tests-green',
    'reviewed',
    'ported',
    'switched',
  ]

  return order
    .map(state => ({ state, count: tiles.filter(tile => tile.state === state).length }))
    .filter(entry => entry.count > 0)
}

/** `0x00RRGGBB` as the `#rrggbb` a `Text`'s `color` takes. */
export const hexOf = (color: number): string => `#${(color & 0xffffff).toString(16).padStart(6, '0')}`
