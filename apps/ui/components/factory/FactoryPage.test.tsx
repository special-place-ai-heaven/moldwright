// @vitest-environment happy-dom
import { act, createElement } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { FactoryControlsView, WorkOrderInput } from '@/app/api/_services/factory-controls.service'

const mocks = vi.hoisted(() => ({
    answer: null as unknown,
    controls: null as FactoryControlsView | null,
    createOrder: vi.fn(async (input: WorkOrderInput) => {
        const order = { ...input, id: 'test-order', status: 'active' as const, action: null, created_at: new Date(Date.now() - 1000).toISOString(), cancelled_at: null }
        mocks.controls = { ...mocks.controls!, orders: [order] }
        return { ok: true as const, order }
    }),
    setState: vi.fn(async (state: FactoryControlsView['state']) => {
        mocks.controls = { ...mocks.controls!, state, stateAt: new Date().toISOString() }
        return { ok: true as const }
    }),
    world: { current: null as null | Record<string, unknown> },
    board: {
        agents: [] as { id: string; name: string; handle?: string }[],
        hydrated: false,
        selectedAgentId: null as string | null,
        hydrate: vi.fn(),
        focusAgentOnBoard: vi.fn(),
    },
    workspace: { id: 7 } as { id: number } | null,
    theme: 'dark' as string | undefined,
}))

const memberControls: FactoryControlsView = {
    isOwner: false, activeRepo: null, state: null, stateAt: null, providersOff: [], throttle: null, projectLimits: null, orders: [],
}

vi.mock('@/app/api/_actions/factory.actions', () => ({
    readFactorySnapshotAction: () => Promise.resolve(mocks.answer),
    listFactoryProjectsAction: () => Promise.resolve({ ok: true, projects: [], isOwner: false }),
    readFactoryControlsAction: () => Promise.resolve({ ok: true, controls: structuredClone(mocks.controls ?? memberControls) }),
    createFactoryWorkOrderAction: mocks.createOrder,
    setFactoryStateAction: mocks.setState,
    setFactoryPoolAction: vi.fn(),
    setFactorySeatsAction: vi.fn(),
}))
vi.mock('@/components/factory/FactoryWorld', () => ({
    FactoryWorld: (props: Record<string, unknown>) => {
        mocks.world.current = props
        return createElement('div', { 'data-world': '', 'data-selected': String(props.selectedIssue ?? '') }, props.topBar as never)
    },
}))
vi.mock('@/components/agent/AgentPanel', () => ({ AgentPanel: () => createElement('div', { 'data-agent-panel': '' }) }))
vi.mock('@/components/layout/WorkspaceSwitcher', () => ({ WorkspaceSwitcher: () => createElement('div', { 'data-workspace-switcher': '' }) }))
vi.mock('@/components/control-center/ControlCenter', () => ({ ControlCenter: () => createElement('div', { 'data-control-center': '' }) }))
vi.mock('next-themes', () => ({ useTheme: () => ({ resolvedTheme: mocks.theme }) }))
vi.mock('@/stores/board.store', () => ({
    useBoardStore: Object.assign((select: (s: typeof mocks.board) => unknown) => select(mocks.board), { getState: () => mocks.board }),
}))
vi.mock('@/supabase/session/SessionProvider', () => ({ useSession: () => ({ workspace: mocks.workspace }) }))

import { toast } from 'sonner'
import { FACTORY_OVERLAY_BELOW, SIDE_PANEL_GAP, loadSidePanelWidth } from '@/lib/side-panel-width'
import { FactoryPage } from './FactoryPage'

const NOW = Date.parse('2026-11-14T12:00:00Z')
const iso = (ms: number) => new Date(ms).toISOString()
const job = (issue: number, over: Record<string, unknown> = {}) => ({
    issue, title: `Job ${issue}`, state: 'building', enteredAt: iso(NOW - 12_000), pr: null, round: null,
    coworker: null, copy: null, steps: null, tokensIn: null, tokensOut: null, parent: null, dependsOn: [], reason: null, ...over,
})
const snapshotWith = (jobs: unknown[], coworkers: unknown[] = [{ name: 'code', id: 'c1', runs: 1, out: 0 }]) => ({
    snapshot: {
        repo: 'o/r', jobs, pools: [{ name: 'build', coworkers }], holds: [],
        endedToday: { merged: 0, rejected: 0, blocked: 0, failed: 0, returned: 0 },
    },
    receivedAt: NOW, ageMs: 0,
})

let host: HTMLDivElement
let root: Root
const flush = () => act(async () => { await Promise.resolve(); await Promise.resolve() })
const mount = async () => { await act(async () => { root.render(createElement(FactoryPage)) }); await flush() }
const remount = async () => { act(() => root.unmount()); root = createRoot(host); await mount() }
const world = () => mocks.world.current as { selectedIssue: number | null; onSelectJob: (n: number) => void; onOpenCoworker: (n: string) => void }
const byText = (sel: string, text: string) => Array.from(host.querySelectorAll<HTMLElement>(sel)).find(e => e.textContent?.trim() === text)
const click = (el: Element | undefined) => act(() => { el!.dispatchEvent(new MouseEvent('click', { bubbles: true })) })

beforeEach(() => {
    host = document.createElement('div')
    document.body.appendChild(host)
    root = createRoot(host)
    ;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
    mocks.answer = null
    mocks.controls = null
    mocks.createOrder.mockClear()
    mocks.setState.mockClear()
    mocks.world.current = null
    mocks.workspace = { id: 7 }
    mocks.theme = 'dark'
    Object.assign(mocks.board, { agents: [], hydrated: false, selectedAgentId: null })
    mocks.board.hydrate.mockReset()
    mocks.board.focusAgentOnBoard.mockReset()
})
afterEach(() => {
    act(() => root.unmount())
    host.remove()
})

describe('factory page', () => {
    it('shows issue intake, the Start request and dispatcher hold after a reload', async () => {
        let reportAt = Date.now() - 2000
        const appliedAt = iso(reportAt - 1000)
        const base = snapshotWith([])
        mocks.answer = {
            ...base,
            snapshot: {
                ...base.snapshot, madeAt: iso(reportAt),
                control: { state: 'STOPPED', at: appliedAt, by: 'private actor' },
                holds: [{ kind: 'stopped', until: iso(reportAt + 60_000) }],
            },
        }
        mocks.controls = { isOwner: true, activeRepo: 'o/r', state: null, stateAt: null, providersOff: [], throttle: null, projectLimits: null, orders: [] }
        await mount()

        click(host.querySelector('[data-order-trigger="ask"]')!)
        click(document.querySelector('[data-order-kind="issue"]')!)
        const input = document.querySelector<HTMLInputElement>('#factory-order-issue')!
        act(() => {
            Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(input, '42')
            input.dispatchEvent(new Event('input', { bubbles: true }))
        })
        const submit = input.closest('form')!.querySelector<HTMLButtonElement>('[type="submit"]')!
        expect(submit.disabled).toBe(false)
        await act(async () => { submit.click() })
        expect(mocks.createOrder).toHaveBeenCalledWith({ repo: 'o/r', kind: 'issue', issues: [42], text: '' })
        act(() => document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true })))

        const start = host.querySelector<HTMLButtonElement>('[data-state-button="RUNNING"]')!
        expect(start.getAttribute('aria-disabled')).toBeNull()
        await act(async () => { start.click() })
        expect(mocks.setState).toHaveBeenCalledWith('RUNNING')
        const requestAt = mocks.controls.stateAt!
        click(host.querySelector('[data-activity]')!)
        const feed = () => document.querySelector<HTMLElement>('section[aria-label="Activity"]')!
        expect(feed().textContent).toContain('Issue added#42')
        expect(feed().textContent).toContain('Start requested')
        expect(feed().textContent).toContain('Dispatcher applied: Stopped')
        expect(feed().textContent).toContain('Held: factory stopped')
        expect(feed().textContent).not.toContain('private actor')
        expect(feed().querySelector(`time[datetime="${requestAt}"]`)).not.toBeNull()
        expect(feed().querySelector(`time[datetime="${appliedAt}"]`)).not.toBeNull()
        expect(feed().textContent).not.toContain('Dispatcher applied: Running')

        reportAt = Date.parse(requestAt) + 1000
        const completed = (mocks.answer as typeof base).snapshot
        mocks.answer = {
            ...base,
            snapshot: {
                ...completed, madeAt: iso(reportAt),
                jobs: [job(42, { state: 'queued', enteredAt: iso(reportAt) })],
                work_order: { ...mocks.controls.orders[0], at: iso(reportAt), current: 42, done: [], skipped: [], halted: null, wait: null },
            },
        }
        await remount()
        click(host.querySelector('[data-activity]')!)
        expect(feed().textContent).toContain('Issue added#42')
        expect(feed().textContent).toContain('Start requested')
        expect(feed().textContent).toContain('Dispatcher accepted the work order')
        expect(feed().textContent).toContain('Held: factory stopped')
        click(feed().querySelector('button')!)
        expect(world().selectedIssue).toBe(42)
    })

    it('a state change made elsewhere is re-read when the factory reports it, so the pill shows no stale ask', async () => {
        vi.useFakeTimers({ toFake: ['setInterval'] })
        try {
            const base = snapshotWith([])
            const reported = (state: string, at: string) => ({ ...base, snapshot: { ...base.snapshot, control: { state, at, by: 'owner' } } })
            mocks.answer = reported('RUNNING', iso(NOW - 60_000))
            mocks.controls = { isOwner: true, activeRepo: 'o/r', state: 'RUNNING', stateAt: iso(NOW - 61_000), providersOff: [], throttle: null, projectLimits: null, orders: [] }
            await mount()
            const pill = () => host.querySelector<HTMLElement>('[data-state-pill]')!
            expect(pill().dataset.statePill).toBe('RUNNING')

            mocks.controls = { ...mocks.controls, state: 'STOPPED', stateAt: iso(NOW - 2000) }
            mocks.answer = reported('STOPPED', iso(NOW - 1000))
            await act(async () => { vi.advanceTimersByTime(30_000) })
            await flush()
            expect(pill().dataset.statePill).toBe('STOPPED')
        } finally {
            vi.useRealTimers()
        }
    })

    it('Stop and Start: busy while sent, the ask pulses until the factory reports it, a failed send frees the controls', async () => {
        vi.useFakeTimers({ toFake: ['setInterval'] })
        const failed = vi.spyOn(toast, 'error').mockImplementation(() => '')
        try {
            const base = snapshotWith([])
            const order = { id: 'o1', repo: 'o/r', kind: 'issue' as const, issues: [42], text: '', status: 'active' as const, action: null, created_at: iso(NOW - 5000), cancelled_at: null }
            const report = async (state: string, at: number, jobs: unknown[] = []) => {
                mocks.answer = { ...base, snapshot: { ...base.snapshot, jobs, control: { state, at: iso(at), by: 'owner' } } }
                await act(async () => { vi.advanceTimersByTime(30_000) })
                await flush()
            }
            mocks.answer = { ...base, snapshot: { ...base.snapshot, jobs: [job(42, { state: 'queued' })], control: { state: 'RUNNING', at: iso(NOW - 60_000), by: 'owner' } } }
            mocks.controls = { isOwner: true, activeRepo: 'o/r', state: 'RUNNING', stateAt: iso(NOW - 61_000), providersOff: [], throttle: null, projectLimits: null, orders: [order] }
            await mount()
            const pill = () => host.querySelector<HTMLElement>('[data-state-pill]')!
            const busy = () => host.querySelector('[role="group"][aria-busy]')!.getAttribute('aria-busy')
            const locked = () => Array.from(host.querySelectorAll<HTMLButtonElement>('[data-state-button], [data-more-controls]')).map(b => b.disabled)
            const loader = () => (world() as unknown as { scene: (t: number, now: number) => { tiles: { id: string; style: { status?: { labelKey?: string } } }[] } })
                .scene(0, Date.now()).tiles.find(t => t.id === 'Delegator')!.style.status?.labelKey
            const press = (state: string) => act(async () => { host.querySelector<HTMLButtonElement>(`[data-state-button="${state}"]`)!.click() })
            expect(loader()).toBe('working')

            let land!: () => void
            mocks.setState.mockImplementationOnce(state => new Promise(done => { land = () => { mocks.controls = { ...mocks.controls!, state, stateAt: iso(NOW) }; done({ ok: true }) } }))
            await press('DRAINING')
            expect(busy()).toBe('true')
            expect(locked()).toEqual([true, true, true, true, true])
            await act(async () => { land() })
            await flush()
            expect(busy()).toBe('false')
            expect(locked()).toEqual([false, false, false, false, false])
            expect(pill().dataset.statePill).toBe('asked')
            expect(pill().querySelector('.animate-pulse')).not.toBeNull()

            await report('STOPPED', NOW)
            expect(pill().dataset.statePill).toBe('STOPPED')
            expect(pill().querySelector('.animate-pulse')).toBeNull()
            expect(loader()).toBeUndefined()

            mocks.setState.mockRejectedValueOnce(new Error('offline'))
            await press('RUNNING')
            await flush()
            expect(failed).toHaveBeenCalledOnce()
            expect(busy()).toBe('false')
            expect(locked()).toEqual([false, false, false, false, false])
            expect(pill().dataset.statePill).toBe('STOPPED')

            await press('RUNNING')
            await flush()
            expect(mocks.setState).toHaveBeenLastCalledWith('RUNNING')
            expect(pill().dataset.statePill).toBe('asked')
            await report('RUNNING', NOW + 1000)
            expect(pill().dataset.statePill).toBe('RUNNING')
            expect(pill().querySelector('.animate-pulse')).toBeNull()
        } finally {
            failed.mockRestore()
            vi.useRealTimers()
        }
    })

    it('mounts the coworker panel', async () => {
        await mount()
        expect(host.querySelector('[data-agent-panel]')).not.toBeNull()
    })

    it('has no Tasks or Inspect column: no [data-column], no [data-rail]', async () => {
        await mount()
        expect(host.querySelector('[data-column]')).toBeNull()
        expect(host.querySelector('[data-rail]')).toBeNull()
        expect(byText('button', 'Tasks')).toBeUndefined()
        expect(byText('button', 'Inspect')).toBeUndefined()
    })

    it('hands FactoryWorld a topBar', async () => {
        await mount()
        expect(mocks.world.current!.topBar).toBeTruthy()
        expect(host.querySelector('[data-topbar]')).not.toBeNull()
    })

    it("the coworker panel's width becomes rightInset while a coworker is selected, 0 when none or when the chat overlays the board", async () => {
        window.innerWidth = 1400
        await mount()
        expect(mocks.world.current!.rightInset).toBe(0)
        mocks.board.selectedAgentId = 'c1'
        await remount()
        expect(mocks.world.current!.rightInset).toBe(loadSidePanelWidth(1400, true) + SIDE_PANEL_GAP)
        window.innerWidth = FACTORY_OVERLAY_BELOW
        await act(async () => { window.dispatchEvent(new Event('resize')) })
        expect(mocks.world.current!.rightInset).toBe(loadSidePanelWidth(FACTORY_OVERLAY_BELOW, true) + SIDE_PANEL_GAP)
        window.innerWidth = FACTORY_OVERLAY_BELOW - 1
        await act(async () => { window.dispatchEvent(new Event('resize')) })
        expect(mocks.world.current!.rightInset).toBe(0)
        window.innerWidth = 1024
    })

    it('hydrates the board store once when it is not hydrated, and not when it is', async () => {
        await mount()
        await act(async () => { root.render(createElement(FactoryPage)) })
        expect(mocks.board.hydrate).toHaveBeenCalledTimes(1)
        expect(mocks.board.hydrate).toHaveBeenCalledWith(7)
        mocks.board.hydrate.mockReset()
        mocks.board.hydrated = true
        await remount()
        expect(mocks.board.hydrate).not.toHaveBeenCalled()
    })

    it('selecting a job in the dropped list selects it for the card and the floor', async () => {
        mocks.answer = snapshotWith([job(11), job(12)])
        await mount()
        await click(host.querySelector('[data-chip="running"]')!)
        await click(host.querySelector('[data-task="11"]')!)
        expect(world().selectedIssue).toBe(11)
        expect(host.querySelector('[data-world]')?.getAttribute('data-selected')).toBe('11')
        expect(host.querySelector('[data-dropdown]')?.textContent).toContain('Job 11')
    })

    it('Escape clears the selection', async () => {
        mocks.answer = snapshotWith([job(11)])
        await mount()
        await act(async () => { world().onSelectJob(11) })
        expect(world().selectedIssue).toBe(11)
        await act(async () => { window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' })) })
        expect(world().selectedIssue).toBeNull()
    })

    it('a sphere click from the floor selects the job', async () => {
        mocks.answer = snapshotWith([job(11), job(12)])
        await mount()
        await act(async () => { world().onSelectJob(12) })
        expect(world().selectedIssue).toBe(12)
    })

    it('a coworker click from the floor opens its panel', async () => {
        mocks.answer = snapshotWith([job(11)])
        await mount()
        await act(async () => { world().onOpenCoworker('code') })
        expect(mocks.board.focusAgentOnBoard).toHaveBeenCalledWith('c1', 'logs')
        mocks.board.focusAgentOnBoard.mockReset()
        await act(async () => { world().onOpenCoworker('nobody') })
        expect(mocks.board.focusAgentOnBoard).not.toHaveBeenCalled()
        mocks.answer = snapshotWith([job(11)], [{ name: 'code', runs: 1, out: 0 }])
        await remount()
        await act(async () => { world().onOpenCoworker('code') })
        expect(mocks.board.focusAgentOnBoard).not.toHaveBeenCalled()
    })

    it('renders the corner menu and the Control Center', async () => {
        await mount()
        expect(host.querySelector('[data-workspace-switcher]')).not.toBeNull()
        expect(host.querySelector('[data-control-center]')).not.toBeNull()
    })

    it('puts Talk to Boss and the corner menu in the top bar, and it still opens the chat of boss', async () => {
        mocks.board.agents = [{ id: 'b1', name: 'x', handle: 'Boss' }]
        await mount()
        const btn = byText('button', 'Talk to Boss') as HTMLButtonElement
        expect(btn.closest('[data-topbar]')).not.toBeNull()
        expect(btn.getAttribute('aria-label')).toBe('Talk to Boss')
        expect(host.querySelector('[data-workspace-switcher]')?.closest('[data-topbar]')).not.toBeNull()
        await click(btn)
        expect(mocks.board.focusAgentOnBoard).toHaveBeenCalledWith('b1', 'chat')
    })

    it('hands FactoryWorld the theme: light when the theme is light, dark otherwise', async () => {
        mocks.theme = 'light'
        await mount()
        expect(mocks.world.current!.theme).toBe('light')
        mocks.theme = 'dark'
        await remount()
        expect(mocks.world.current!.theme).toBe('dark')
        mocks.theme = undefined
        await remount()
        expect(mocks.world.current!.theme).toBe('dark')
    })

    it('Talk to Boss opens the chat of the coworker named boss, and is disabled when there is none', async () => {
        await mount()
        const none = byText('button', 'Talk to Boss') as HTMLButtonElement
        expect(none.getAttribute('aria-disabled')).toBe('true')
        expect(none.disabled).toBe(false)
        await click(none)
        expect(mocks.board.focusAgentOnBoard).not.toHaveBeenCalled()
        mocks.board.agents = [{ id: 'a1', name: 'Other' }, { id: 'b1', name: 'x', handle: 'Boss' }]
        await remount()
        const btn = byText('button', 'Talk to Boss') as HTMLButtonElement
        expect(btn.getAttribute('aria-disabled')).toBe('false')
        await click(btn)
        expect(mocks.board.focusAgentOnBoard).toHaveBeenCalledWith('b1', 'chat')
    })

    it('Open on a run opens that coworker on its logs', async () => {
        const run = { stage: 'build', coworkerId: 'c1', status: 'ok', startedAt: iso(NOW - 60_000), endedAt: iso(NOW - 30_000), tokensIn: 1, tokensOut: 2, runId: null }
        mocks.answer = snapshotWith([job(11, { runs: [run] })])
        await mount()
        await act(async () => { world().onSelectJob(11) })
        await click(byText('button', 'Open'))
        expect(mocks.board.focusAgentOnBoard).toHaveBeenCalledWith('c1', 'logs')
    })

    it('hands the live snapshot to the floor for the bar, and null before it arrives', async () => {
        await mount()
        expect(mocks.world.current!.snapshot).toBeNull()
        mocks.answer = snapshotWith([job(1)])
        await remount()
        expect(mocks.world.current!.snapshot).toEqual((mocks.answer as { snapshot: unknown }).snapshot)
    })
})
