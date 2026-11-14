// The factory as a scene of the board's own world: rooms are containers, coworkers are buddies, the
// extra runs of a coworker are see-through copies of its buddy, and each job is a crate that hops
// from room to room along the corridor (row 4). `factoryScene(t)` is a pure function of the time in
// the loop, so a frame is the same however often it is drawn.
// shortcut: the jobs are a fixed sample loop; the real page feeds the delegator's ledger instead.

import { agentTileStyle, type BuddyLook, type Container, type Tile, type TileLink, type TileResultItem, type TileToast } from '@rerun/ui/iso-grid'

type Cell = { col: number; row: number }

export const LOOP_MS = 84_000
const HOP_MS = 230
const CORRIDOR = 6
const HOLD = { from: 44_000, to: 54_000 }

const ROOMS: Container[] = [
    { id: 'build', label: 'Build bay', color: '#fde7c8', col_start: 0, row_start: 0, col_end: 5, row_end: 5 },
    { id: 'review', label: 'Review', color: '#c9f0dd', col_start: 6, row_start: 0, col_end: 11, row_end: 5 },
    { id: 'intake', label: 'Intake', color: '#e7e5e4', col_start: 0, row_start: 7, col_end: 2, row_end: 11 },
    { id: 'studio', label: 'Studio', color: '#fbd5e8', col_start: 3, row_start: 7, col_end: 6, row_end: 11 },
    { id: 'checks', label: 'Checks', color: '#d9dcfb', col_start: 7, row_start: 7, col_end: 9, row_end: 11 },
    { id: 'shipped', label: 'Shipped', color: '#c8f2d2', col_start: 10, row_start: 7, col_end: 11, row_end: 11 },
]

// One look per coworker, shared by its copies: a copy is the same buddy, fainter.
const LOOKS: Record<string, BuddyLook> = {
    code: { eyes: 'visor', mouth: 'smile', color: '#4d34f7' },
    LARRY: { eyes: 'glasses', mouth: 'flat', color: '#0ea5e9' },
    LINUS: { eyes: 'brows', mouth: 'flat', color: '#10b981' },
    BRUCE: { eyes: 'shades', mouth: 'none', color: '#64748b' },
    search: { eyes: 'round', mouth: 'open', color: '#f472b6' },
    DIETER: { eyes: 'sparkle', mouth: 'cat', color: '#f59e0b' },
}

const MAIN: Record<string, Cell> = {
    code: { col: 2, row: 2 }, LARRY: { col: 0, row: 0 },
    LINUS: { col: 8, row: 2 }, BRUCE: { col: 10, row: 0 },
    search: { col: 3, row: 8 }, DIETER: { col: 5, row: 10 },
}
const MAIN_ROOM: Record<string, string> = { code: 'build', LARRY: 'build', LINUS: 'review', BRUCE: 'review', search: 'studio', DIETER: 'studio' }

// The copies stand around their coworker. A crate walks the conveyor (row 6) to the door of a
// room, the door cell of a column, and is taken in there.
const INTAKE_SLOTS: Cell[] = [8, 9, 10, 11].flatMap(row => [0, 1, 2].map(col => ({ col, row })))
const BUILD_SLOTS: Cell[] = [{ col: 1, row: 2 }, { col: 1, row: 3 }, { col: 4, row: 2 }, { col: 4, row: 3 }, { col: 2, row: 4 }, { col: 3, row: 4 }]
const LARRY_SLOT: Cell = { col: 0, row: 2 }
const REVIEW_SLOTS: Cell[] = [{ col: 8, row: 4 }, { col: 9, row: 4 }, { col: 10, row: 3 }]
const BRUCE_SLOT: Cell = { col: 10, row: 2 }
const CHECK_SLOTS: Cell[] = [{ col: 7, row: 8 }, { col: 8, row: 8 }, { col: 9, row: 8 }, { col: 7, row: 10 }]
const GATE: Cell = { col: 8, row: 9 }
const DOCK: Cell = { col: 10, row: 9 }
const ARRIVAL: Cell = { col: 10, row: 7 }
const HOPPER: Cell = { col: 0, row: 7 }
const SEARCH_SLOTS: Cell[] = [{ col: 5, row: 8 }, { col: 6, row: 8 }]
const door = (c: Cell): Cell => ({ col: c.col, row: c.row < CORRIDOR ? CORRIDOR - 1 : CORRIDOR + 1 })

type JobSpec = { issue: number; pr: number; title: string; start: number; queue: number; build: number; review: number; checks: number }

// A wave of seven: six builds at once on `code`, the seventh on LARRY behind it. Three more land
// while sending is held and leave when the hold ends.
const SPEC: JobSpec[] = [
    { issue: 330, pr: 340, title: 'Factory view: rooms', start: 0, queue: 1_200, build: 13_000, review: 4_500, checks: 5_000 },
    { issue: 331, pr: 341, title: 'Ledger read route', start: 500, queue: 1_200, build: 16_500, review: 5_000, checks: 5_500 },
    { issue: 332, pr: 342, title: 'Heartbeat endpoint', start: 1_000, queue: 1_200, build: 11_000, review: 4_000, checks: 5_000 },
    { issue: 333, pr: 343, title: 'Hold band', start: 1_500, queue: 1_200, build: 19_000, review: 5_500, checks: 6_000 },
    { issue: 334, pr: 344, title: 'Copies as ghosts', start: 2_000, queue: 1_200, build: 15_000, review: 4_500, checks: 5_000 },
    { issue: 335, pr: 345, title: 'Gauges', start: 2_500, queue: 1_200, build: 22_000, review: 5_000, checks: 5_500 },
    { issue: 336, pr: 346, title: 'Crate paths', start: 3_000, queue: 1_200, build: 17_000, review: 5_000, checks: 5_000 },
    { issue: 337, pr: 347, title: 'Merge confetti', start: 45_000, queue: 0, build: 9_000, review: 3_500, checks: 4_000 },
    { issue: 338, pr: 348, title: 'Studio room', start: 46_000, queue: 0, build: 10_000, review: 3_500, checks: 4_000 },
    { issue: 339, pr: 349, title: 'Phone width', start: 47_000, queue: 0, build: 8_500, review: 3_500, checks: 4_000 },
]

function path(a: Cell, b: Cell): Cell[] {
    const from = door(a), to = door(b)
    const cells: Cell[] = [from, { col: from.col, row: CORRIDOR }]
    let col = from.col
    while (col !== to.col) { col += to.col > col ? 1 : -1; cells.push({ col, row: CORRIDOR }) }
    cells.push(to)
    return cells
}

type Leg = { kind: 'wait' | 'walk' | 'build' | 'review' | 'checks' | 'done'; from: number; to: number; at?: Cell; cells?: Cell[] }
type Job = JobSpec & { builder: 'code' | 'LARRY'; copy: number; buildAt: Cell; reviewer: 'LINUS' | 'BRUCE'; reviewCopy: number; reviewAt: Cell; legs: Leg[]; mergedAt: number; prAt: number }

function plan(): Job[] {
    const freeFrom = new Map<string, number>()
    const take = (count: number, at: number, prefix: string) => {
        for (let i = 0; i < count; i++) if ((freeFrom.get(`${prefix}${i}`) ?? 0) <= at) { freeFrom.set(`${prefix}${i}`, Infinity); return i }
        return -1
    }
    return SPEC.map((spec, n) => {
        const intake = INTAKE_SLOTS[n % INTAKE_SLOTS.length]
        let t = spec.start + spec.queue
        if (t < HOLD.to && t + 1 > HOLD.from - 4_000 && spec.start >= HOLD.from - 4_000) t = HOLD.to + (n % 3) * 500
        const legs: Leg[] = [{ kind: 'wait', from: spec.start, to: t, at: intake }]
        const walk = (a: Cell, b: Cell) => { const cells = path(a, b); legs.push({ kind: 'walk', from: t, to: t + cells.length * HOP_MS, cells }); t += cells.length * HOP_MS }

        const copyIdx = take(BUILD_SLOTS.length, t, 'b')
        const builder = copyIdx < 0 ? 'LARRY' : 'code'
        const buildAt = copyIdx < 0 ? LARRY_SLOT : BUILD_SLOTS[copyIdx]
        walk(intake, buildAt)
        legs.push({ kind: 'build', from: t, to: t + spec.build, at: buildAt }); t += spec.build
        if (copyIdx >= 0) freeFrom.set(`b${copyIdx}`, t)
        const prAt = t

        const reviewIdx = take(REVIEW_SLOTS.length, t, 'r')
        const reviewer = reviewIdx < 0 ? 'BRUCE' : 'LINUS'
        const reviewAt = reviewIdx < 0 ? BRUCE_SLOT : REVIEW_SLOTS[reviewIdx]
        walk(buildAt, reviewAt)
        legs.push({ kind: 'review', from: t, to: t + spec.review, at: reviewAt }); t += spec.review
        if (reviewIdx >= 0) freeFrom.set(`r${reviewIdx}`, t)

        const checkIdx = Math.max(0, take(CHECK_SLOTS.length, t, 'c'))
        const checkAt = CHECK_SLOTS[checkIdx]
        walk(reviewAt, checkAt)
        legs.push({ kind: 'checks', from: t, to: t + spec.checks, at: checkAt }); t += spec.checks
        freeFrom.set(`c${checkIdx}`, t)
        walk(checkAt, ARRIVAL)
        legs.push({ kind: 'done', from: t, to: Infinity })
        return { ...spec, builder, copy: copyIdx + 1, buildAt, reviewer, reviewCopy: reviewIdx + 1, reviewAt, legs, mergedAt: t, prAt }
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
    counts: { waiting: number; building: number; review: number; checks: number; merged: number }
    copies: { code: number; LINUS: number; search: number }
    // Label to merge of each job merged so far in the loop, ms of the loop.
    leadMs: number[]
}

function crate(issue: number, cell: Cell, placed: boolean, label: string, held: boolean): Tile {
    return {
        id: `crate-${issue}`, position: cell, span: 1, selectable: false, draggable: false, justPlaced: placed,
        style: { color: held ? '#94a3b8' : '#c8925a', sheen: true, depth: 0.55, label, badge: held ? 'lock' : null, stripes: held || undefined,
            status: { label, tone: 'neutral' } },
        ariaLabel: label,
    }
}

function copyTile(id: string, who: string, cell: Cell, room: string, label: string, placed: boolean): Tile {
    return {
        id, position: cell, span: 1, containerId: room, selectable: false, draggable: false, justPlaced: placed,
        style: { ...agentTileStyle('working', who), opacity: 0.62, label, buddy: { ...LOOKS[who], mood: 'working', footprintShare: 0.9 },
            status: { label, tone: 'orange', pinned: { label, spinner: true } } },
        ariaLabel: `${who}, ${label}`,
    }
}

export function factoryScene(t: number, now: number): FactoryFrame {
    const held = t >= HOLD.from && t < HOLD.to
    const tiles: Tile[] = []
    const links: TileLink[] = []
    const toasts: TileToast[] = []
    const working = new Set<string>()
    const counts = { waiting: 0, building: 0, review: 0, checks: 0, merged: 0 }
    const copies = { code: 0, LINUS: 0, search: 0 }
    const leadMs: number[] = []
    const merges: TileResultItem[] = []
    let gateUntil = 0
    const toast = (at: number, tileId: string, author: string, message: string) => {
        if (t >= at && t < at + 3_200) toasts.push({ id: `${tileId}-${at}`, tileId, author, message })
    }

    for (const job of JOBS) {
        if (t < job.start) continue
        if (t >= job.mergedAt) {
            counts.merged++
            leadMs.push(job.mergedAt - job.start)
            merges.push({ label: `#${job.issue} ${job.title}`, count: 1, at: now - (t - job.mergedAt) })
            toast(job.mergedAt, 'dock', 'Shipped', `PR #${job.pr} merged into dev`)
            continue
        }
        const leg = job.legs.find(l => t >= l.from && t < l.to)
        if (!leg) continue
        if (leg.kind === 'wait') {
            counts.waiting++
            tiles.push(crate(job.issue, leg.at!, t - job.start < 900, `#${job.issue}`, held))
        } else if (leg.kind === 'walk') {
            const cells = leg.cells!
            const cell = cells[Math.min(cells.length - 1, Math.floor((t - leg.from) / HOP_MS))]
            tiles.push(crate(job.issue, cell, false, t >= job.prAt ? `PR #${job.pr}` : `#${job.issue}`, false))
        } else if (leg.kind === 'build') {
            counts.building++
            working.add(job.builder)
            const id = job.builder === 'code' ? `copy-${job.issue}` : 'LARRY'
            if (job.builder === 'code') {
                copies.code++
                tiles.push(copyTile(id, 'code', job.buildAt, 'build', `#${job.issue}`, t - leg.from < 900))
                links.push({ source: 'code', target: id, variant: 'cable' })
            }
            toast(leg.to - 3_000, id, job.builder, `PR #${job.pr} opened`)
        } else if (leg.kind === 'review') {
            counts.review++
            working.add(job.reviewer)
            const id = job.reviewer === 'LINUS' ? `review-${job.issue}` : 'BRUCE'
            if (job.reviewer === 'LINUS') {
                copies.LINUS++
                tiles.push(copyTile(id, 'LINUS', job.reviewAt, 'review', `PR #${job.pr}`, t - leg.from < 900))
                links.push({ source: 'LINUS', target: id, variant: 'cable' })
            }
            links.push({ source: 'code', target: id })
            toast(leg.to - 2_800, id, job.reviewer, `PR #${job.pr} approved`)
        } else if (leg.kind === 'checks') {
            counts.checks++
            gateUntil = Math.max(gateUntil, leg.to)
            tiles.push(crate(job.issue, leg.at!, false, `PR #${job.pr}`, false))
            links.push({ source: 'gate', target: `crate-${job.issue}`, variant: 'cable' })
        }
    }

    // The coworkers. A main buddy works while any of its runs does; LARRY and BRUCE wait behind, faded.
    const searchBusy = t % 30_000 < 16_000
    for (const who of Object.keys(MAIN)) {
        const busy = working.has(who) || (who === 'search' && searchBusy) || (who === 'DIETER' && t % 26_000 > 12_000)
        const behind = (who === 'LARRY' || who === 'BRUCE') && !busy
        tiles.push({ id: who, position: MAIN[who], span: 2, containerId: MAIN_ROOM[who], selectable: false, draggable: false,
            style: { ...agentTileStyle(busy ? 'working' : 'idle', who), buddy: { ...LOOKS[who] }, ...(behind ? { opacity: 0.5 } : {}) }, ariaLabel: who })
    }
    if (searchBusy) {
        for (const [n, cell] of SEARCH_SLOTS.entries()) {
            const id = `search-copy-${n}`
            copies.search++
            tiles.push(copyTile(id, 'search', cell, 'studio', 'research', t % 30_000 < 900))
            links.push({ source: 'search', target: id, variant: 'cable' })
        }
    }

    // The checks gate, the dock with what shipped, and the intake hopper that locks while sending is held.
    tiles.push({ id: 'gate', position: GATE, span: 2, containerId: 'checks', selectable: false, draggable: false,
        style: { color: gateUntil ? '#6366f1' : '#94a3b8', glow: gateUntil ? 'rgba(99,102,241,0.55)' : undefined, shimmer: !!gateUntil, stripes: true, sheen: true, label: 'Checks',
            ...(gateUntil ? { countdown: { at: now + (gateUntil - t) } } : {}) }, ariaLabel: 'Checks gate' })
    tiles.push({ id: 'dock', position: DOCK, span: 1, containerId: 'shipped', selectable: false, draggable: false,
        style: { color: '#22c55e', glow: 'rgba(34,197,94,0.55)', sheen: true, label: 'Shipped',
            ...(merges.length ? { results: { count: merges.length, items: merges.slice(-6).reverse() } } : {}) }, ariaLabel: 'Shipped' })
    tiles.push({ id: 'hopper', position: HOPPER, span: 1, containerId: 'intake', selectable: false, draggable: false,
        style: { color: held ? '#ef4444' : '#a3a3a3', errorPulse: held, pingRings: held, badge: held ? 'lock' : null, sheen: true, label: 'Intake' }, ariaLabel: 'Intake' })
    if (held) toast(HOLD.from + 300, 'hopper', 'Delegator', 'Line held: sign-in renewal. Running builds finish.')

    return { containers: ROOMS, tiles, links, toasts, held, holdLeftMs: held ? HOLD.to - t : 0, counts, copies, leadMs }
}
