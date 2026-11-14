// The factory staged as a Rerun board, with the board's own pieces and measures: Boxes on the
// lattice (8 high, a cell apart), coworkers as 2x2 buddies, objects as 1x1 connector tiles with one
// free cell between them and their coworker, on a cable. A copy of a coworker is that coworker's
// buddy, see-through. A job is a GitHub object: it drops in beside whoever holds it, its cable a
// running beam while that one works, so it travels Dispatch -> Build -> Review -> Dispatch.
// Every piece moves the way the board's do: working buddies bob, idle ones blink and glance,
// cables carry their comet, objects under checks breathe a halo.
// `factoryScene(t)` is a pure function of the time in the loop.
// shortcut: the jobs are a fixed sample loop; the real page feeds the delegator's ledger instead.

import { agentTileStyle, connectorTileStyle, type BuddyLook, type Container, type Tile, type TileLink, type TileResultItem, type TileToast } from '@rerun/ui/iso-grid'

type Cell = { col: number; row: number }

export const LOOP_MS = 84_000
const HOLD = { from: 46_000, to: 56_000 }
const GITHUB = '/services/github.svg'

// A 2x2 place every five cells: buddy (2), free cell, its object, free cell.
const PITCH = 5
const box = (id: string, label: string, col: number, row: number, perRow: number): Container =>
    ({ id, label, color: '#ffffff', col_start: col, row_start: row, col_end: col + PITCH * perRow, row_end: row + 7 })
const BOXES: Container[] = [
    box('dispatch', 'Dispatch', 0, 0, 1),
    box('build', 'Build', 7, 0, 4),
    box('review', 'Review', 7, 9, 2),
    box('studio', 'Research & design', 19, 9, 2),
]
const B = (id: string) => BOXES.find(b => b.id === id)!
const places = (b: Container, perRow: number, n: number): Cell[] =>
    Array.from({ length: n }, (_, i) => ({ col: b.col_start + 1 + PITCH * (i % perRow), row: b.row_start + 1 + PITCH * Math.floor(i / perRow) }))
const objectBeside = (p: Cell): Cell => ({ col: p.col + 3, row: p.row + 1 })

const BUILD = places(B('build'), 4, 8)
const REVIEW = places(B('review'), 2, 4)
const STUDIO = places(B('studio'), 2, 4)
const DELEGATOR: Cell = { col: B('dispatch').col_start + 2, row: B('dispatch').row_start + 3 }
// Waiting and checking jobs ring the delegator, a free cell from it and from each other.
const RING: Cell[] = [[0, 1], [2, 1], [4, 1], [0, 6], [2, 6], [4, 6], [0, 3], [5, 3]].map(([c, r]) => ({ col: B('dispatch').col_start + c, row: B('dispatch').row_start + r }))

const LOOKS: Record<string, BuddyLook> = {
    Delegator: { eyes: 'pixel', mouth: 'flat', color: '#334155' },
    code: { eyes: 'visor', mouth: 'smile', color: '#4d34f7' },
    LARRY: { eyes: 'glasses', mouth: 'flat', color: '#0ea5e9' },
    LINUS: { eyes: 'brows', mouth: 'flat', color: '#10b981' },
    BRUCE: { eyes: 'shades', mouth: 'none', color: '#64748b' },
    search: { eyes: 'round', mouth: 'open', color: '#f472b6' },
    DIETER: { eyes: 'sparkle', mouth: 'cat', color: '#f59e0b' },
}

// Build: `code`, its six copies, LARRY behind. Review: LINUS, two copies, BRUCE behind.
// Studio: search, its copy, DIETER.
const CODE = BUILD[0], CODE_COPIES = BUILD.slice(1, 7), LARRY = BUILD[7]
const LINUS = REVIEW[0], LINUS_COPIES = REVIEW.slice(1, 3), BRUCE = REVIEW[3]
const SEARCH = STUDIO[0], SEARCH_COPY = STUDIO[1], DIETER = STUDIO[2]

type JobSpec = { issue: number; pr: number; title: string; start: number; build: number; review: number; checks: number }

// A wave of seven: six builds at once on `code`, the seventh on LARRY. Three more arrive while
// sending is held and go when the hold ends.
const SPEC: JobSpec[] = [
    { issue: 330, pr: 340, title: 'Factory view', start: 0, build: 13_000, review: 4_500, checks: 5_000 },
    { issue: 331, pr: 341, title: 'Ledger read route', start: 400, build: 16_500, review: 5_000, checks: 5_500 },
    { issue: 332, pr: 342, title: 'Heartbeat endpoint', start: 800, build: 11_000, review: 4_000, checks: 5_000 },
    { issue: 333, pr: 343, title: 'Hold band', start: 1_200, build: 19_000, review: 5_500, checks: 6_000 },
    { issue: 334, pr: 344, title: 'Copies', start: 1_600, build: 15_000, review: 4_500, checks: 5_000 },
    { issue: 335, pr: 345, title: 'Gauges', start: 2_000, build: 22_000, review: 5_000, checks: 5_500 },
    { issue: 336, pr: 346, title: 'Job objects', start: 2_400, build: 17_000, review: 5_000, checks: 5_000 },
    { issue: 337, pr: 347, title: 'Merge confetti', start: 47_000, build: 9_000, review: 3_500, checks: 4_000 },
    { issue: 338, pr: 348, title: 'Studio Box', start: 48_000, build: 10_000, review: 3_500, checks: 4_000 },
    { issue: 339, pr: 349, title: 'Phone width', start: 49_000, build: 8_500, review: 3_500, checks: 4_000 },
]
const QUEUE_MS = 2_500

type Stage = 'queued' | 'build' | 'review' | 'checks' | 'merged'
type Job = JobSpec & { times: Record<Stage, number>; builder: string; buildAt: Cell; buildCopy: boolean; reviewer: string; reviewAt: Cell; reviewCopy: boolean; waitAt: Cell; checkAt: Cell }

function plan(): Job[] {
    const freeFrom = new Map<string, number>()
    const take = (keys: string[], t: number) => { const k = keys.find(key => (freeFrom.get(key) ?? 0) <= t); if (k) freeFrom.set(k, Infinity); return k }
    const buildKeys = [...CODE_COPIES.map((_, i) => `c${i}`), 'LARRY']
    const reviewKeys = ['LINUS', ...LINUS_COPIES.map((_, i) => `l${i}`), 'BRUCE']
    const ringFree = new Map<number, number>()
    const ringSlot = (from: number, to: number) => { const i = RING.findIndex((_, n) => (ringFree.get(n) ?? 0) <= from); ringFree.set(i, to); return RING[Math.max(0, i)] }
    return SPEC.map((spec, n) => {
        let t = spec.start + QUEUE_MS
        if (spec.start >= HOLD.from - 2_000 && t < HOLD.to) t = HOLD.to + (n % 3) * 700
        const waitAt = ringSlot(spec.start, t)
        const bk = take(buildKeys, t) ?? 'LARRY'
        const build = t; t += spec.build; freeFrom.set(bk, t)
        const rk = take(reviewKeys, t) ?? 'BRUCE'
        const review = t; t += spec.review; freeFrom.set(rk, t)
        const checks = t; t += spec.checks
        const checkAt = ringSlot(checks, t)
        return {
            ...spec, times: { queued: spec.start, build, review, checks, merged: t }, waitAt, checkAt,
            builder: bk === 'LARRY' ? 'LARRY' : 'code', buildAt: bk === 'LARRY' ? LARRY : CODE_COPIES[Number(bk.slice(1))], buildCopy: bk !== 'LARRY',
            reviewer: rk === 'BRUCE' ? 'BRUCE' : 'LINUS', reviewAt: rk === 'BRUCE' ? BRUCE : rk === 'LINUS' ? LINUS : LINUS_COPIES[Number(rk.slice(1))], reviewCopy: rk.startsWith('l'),
        }
    })
}
export const JOBS = plan()

export type FactoryFrame = {
    containers: Container[]
    tiles: Tile[]
    links: TileLink[]
    toasts: TileToast[]
    held: boolean
    holdLeftMs: number
    counts: { queued: number; building: number; review: number; checks: number; merged: number; runs: number; runsOut: number }
    leadMs: number[]
}

function stageOf(job: Job, t: number): Stage | null {
    if (t < job.times.queued) return null
    if (t >= job.times.merged) return 'merged'
    if (t >= job.times.checks) return 'checks'
    if (t >= job.times.review) return 'review'
    if (t >= job.times.build) return 'build'
    return 'queued'
}

function jobObject(job: Job, stage: Stage, cell: Cell, held: boolean): Tile {
    const label = stage === 'queued' || stage === 'build' ? `#${job.issue}` : `PR #${job.pr}`
    return {
        id: `job-${job.issue}-${stage}`, position: cell, span: 1, selectable: false, draggable: false, justPlaced: true,
        style: { ...connectorTileStyle(GITHUB), label, badge: held ? 'lock' : null },
        // Under checks the object breathes its halo, as a highlighted connector does on the board.
        highlighted: stage === 'checks',
        ariaLabel: `${label}: ${job.title}`,
    }
}

function buddy(id: string, who: string, position: Cell, room: string, state: 'working' | 'idle' | 'waiting_human', opts: { copy?: boolean; behind?: boolean } = {}): Tile {
    const style = agentTileStyle(state, who)
    return {
        id, position, span: 2, containerId: room, selectable: false, draggable: false, justPlaced: !!opts.copy,
        style: { ...style, buddy: { ...LOOKS[who] }, ...(opts.copy ? { opacity: 0.6 } : opts.behind ? { opacity: 0.5 } : {}) },
        ariaLabel: opts.copy ? `${who}, a copy` : who,
    }
}

export function factoryScene(t: number, now: number): FactoryFrame {
    const held = t >= HOLD.from && t < HOLD.to
    const tiles: Tile[] = []
    const links: TileLink[] = []
    const toasts: TileToast[] = []
    const busy = new Set<string>()
    const counts = { queued: 0, building: 0, review: 0, checks: 0, merged: 0, runs: 0, runsOut: 0 }
    const merged: TileResultItem[] = []
    const leadMs: number[] = []
    const toast = (from: number, tileId: string, author: string, message: string) => {
        if (t >= from && t < from + 3_000) toasts.push({ id: `${tileId}@${from}`, tileId, author, message })
    }

    for (const job of JOBS) {
        const stage = stageOf(job, t)
        if (!stage) continue
        counts.runs += (stage === 'queued' ? 0 : 1) + (stage === 'checks' || stage === 'merged' ? 1 : 0)
        if (stage === 'merged') {
            counts.merged++
            leadMs.push(job.times.merged - job.times.queued)
            merged.push({ label: `PR #${job.pr} ${job.title}`, count: 1, at: now - (t - job.times.merged) })
            toast(job.times.merged, 'Delegator', 'Delegator', `Merged PR #${job.pr} into dev`)
            continue
        }
        if (stage === 'queued' || stage === 'checks') {
            counts[stage === 'queued' ? 'queued' : 'checks']++
            const obj = jobObject(job, stage, stage === 'queued' ? job.waitAt : job.checkAt, held && stage === 'queued')
            tiles.push(obj)
            links.push({ source: 'Delegator', target: obj.id, variant: 'cable' })
            continue
        }
        const building = stage === 'build'
        counts[building ? 'building' : 'review']++
        counts.runsOut++
        const who = building ? job.builder : job.reviewer
        const isCopy = building ? job.buildCopy : job.reviewCopy
        const at = building ? job.buildAt : job.reviewAt
        busy.add(who)
        const holder = isCopy ? `${who}-copy-${job.issue}` : who
        if (isCopy) {
            tiles.push(buddy(holder, who, at, building ? 'build' : 'review', 'working', { copy: true }))
            links.push({ source: who, target: holder, variant: 'cable' })
        }
        const obj = jobObject(job, stage, objectBeside(at), false)
        tiles.push(obj)
        links.push({ source: holder, target: obj.id, variant: 'beam' })
        if (building) toast(job.times.review - 2_800, holder, isCopy ? `${who} · copy` : who, `PR #${job.pr} opened`)
        else toast(job.times.checks - 2_600, holder, isCopy ? `${who} · copy` : who, `PR #${job.pr} approved`)
    }

    // The studio keeps a rhythm of its own.
    const researching = t % 30_000 < 16_000
    if (researching) {
        tiles.push(buddy('search-copy', 'search', SEARCH_COPY, 'studio', 'working', { copy: true }))
        links.push({ source: 'search', target: 'search-copy', variant: 'cable' })
    }

    // The coworkers: a main works while any of its runs does; the one behind it waits, faded.
    const state = (who: string) => (busy.has(who) ? 'working' : 'idle') as 'working' | 'idle'
    tiles.push(buddy('code', 'code', CODE, 'build', state('code')))
    tiles.push(buddy('LARRY', 'LARRY', LARRY, 'build', state('LARRY'), { behind: !busy.has('LARRY') }))
    tiles.push(buddy('LINUS', 'LINUS', LINUS, 'review', state('LINUS')))
    tiles.push(buddy('BRUCE', 'BRUCE', BRUCE, 'review', state('BRUCE'), { behind: !busy.has('BRUCE') }))
    tiles.push(buddy('search', 'search', SEARCH, 'studio', researching ? 'working' : 'idle'))
    tiles.push(buddy('DIETER', 'DIETER', DIETER, 'studio', t % 26_000 > 12_000 ? 'working' : 'idle'))

    // The delegator takes the issues, holds them while sending is held, and merges.
    const delegator = buddy('Delegator', 'Delegator', DELEGATOR, 'dispatch', held ? 'waiting_human' : counts.queued + counts.checks > 0 ? 'working' : 'idle')
    if (held) delegator.style = { ...delegator.style, badge: 'lock' }
    if (merged.length && !held) delegator.style = { ...delegator.style, results: { count: merged.length, items: merged.slice(-6).reverse() } }
    tiles.push(delegator)
    if (held) toast(HOLD.from + 300, 'Delegator', 'Delegator', 'Sending held: sign-in renewal. Running builds finish.')

    return { containers: BOXES, tiles, links, toasts, held, holdLeftMs: held ? HOLD.to - t : 0, counts, leadMs }
}
