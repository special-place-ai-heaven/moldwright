// @vitest-environment happy-dom
import { readFileSync } from 'node:fs'
import path from 'node:path'
import { act, createElement } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { factorySnapshotSchema, type FactoryJob, type FactorySnapshot } from '@moldwright/contracts'
import { TooltipProvider } from '@/components/ui/tooltip'
import { FactoryTopBar } from './FactoryTopBar'
import { FactoryWorld } from './FactoryWorld'
import { SAMPLE_TEXT } from './FactoryTasks'
import { sceneFromSnapshot } from './from-snapshot'

vi.mock('@moldwright/ui/iso-grid', async importOriginal => ({ ...(await importOriginal<typeof import('@moldwright/ui/iso-grid')>()), IsoGrid: () => null }))

const ROOT = path.resolve(import.meta.dirname, '../../../..')
const sample = () => factorySnapshotSchema.parse(JSON.parse(readFileSync(path.join(ROOT, 'packages/contracts/fixtures/factory-snapshot.sample.json'), 'utf8')))

const job = (issue: number, over: Partial<FactoryJob> = {}): FactoryJob => ({
    issue, title: `Task ${issue}`, state: 'waiting', enteredAt: new Date().toISOString(), pr: null, round: null,
    coworker: null, copy: null, steps: null, tokensIn: null, tokensOut: null, parent: 1, dependsOn: [], reason: null, ...over,
})
const snapshot = (): FactorySnapshot => ({
    ...sample(),
    madeAt: new Date().toISOString(),
    epics: [{ issue: 1, title: 'Epic one', kind: 'feature' }],
    jobs: [
        job(11, { state: 'building', department: 'engine' }),
        job(12, { state: 'waiting' }),
        job(13, { state: 'blocked', reason: 'no key' }),
        job(14, { state: 'merged' }),
    ],
})

let host: HTMLDivElement
let root: Root
const q = (s: string) => host.querySelector(s) as HTMLElement | null
const chip = (name: string) => host.querySelector(`[data-chip="${name}"]`) as HTMLElement | null
const click = (el: Element | null) => act(() => { el!.dispatchEvent(new MouseEvent('click', { bubbles: true })) })
const render = (over: Record<string, unknown> = {}) => act(() => {
    root.render(createElement(FactoryTopBar, { snapshot: snapshot(), controls: { view: null, loadError: null, reload: async () => {} }, selected: null, onSelect: () => {}, names: {}, onOpenCoworker: () => {}, ...over } as never))
})

beforeEach(() => {
    host = document.createElement('div')
    document.body.appendChild(host)
    root = createRoot(host)
    ;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
})
afterEach(() => { act(() => root.unmount()); host.remove() })

describe('FactoryTopBar', () => {
    it('collapsed: one row of four chips with counts and no panel', () => {
        render()
        expect(Array.from(host.querySelectorAll('[data-chip]')).map(c => c.textContent)).toEqual(['Running 3/1', 'Waiting 1', 'Problems 1', 'Done today 1'])
        expect(q('[data-dropdown]')).toBeNull()
        expect(chip('running')?.getAttribute('aria-pressed')).toBe('false')
    })

    it('a chip drops the ledger down filtered to it, and again closes it', async () => {
        render()
        await click(chip('problems'))
        expect(chip('problems')?.getAttribute('aria-pressed')).toBe('true')
        expect(q('[data-dropdown]')).not.toBeNull()
        expect(q('[data-task="13"]')).not.toBeNull()
        expect(q('[data-task="11"]')).toBeNull()
        await click(chip('problems'))
        expect(q('[data-dropdown]')).toBeNull()
    })

    it('the dropped chip row adds This wave and the departments', async () => {
        render()
        await click(chip('running'))
        const dd = q('[data-dropdown]')!
        expect(dd.querySelector('[data-chip="wave"]')?.textContent).toBe('This wave')
        expect(dd.querySelector('[data-chip="engine"]')).not.toBeNull()
    })

    it('selecting a task drops its card down instead of the ledger', async () => {
        const onSelect = vi.fn()
        render({ onSelect })
        await click(chip('running'))
        await click(q('[data-task="11"]'))
        expect(onSelect).toHaveBeenCalledWith(11)
        render({ onSelect, selected: 11 })
        expect(q('[data-dropdown]')?.textContent).toContain('Task 11')
        expect(q('[data-task="12"]')).toBeNull()
        const back = Array.from(host.querySelectorAll('button')).find(b => b.textContent === 'Back to the list')!
        await click(back)
        expect(onSelect).toHaveBeenLastCalledWith(null)
    })

    it("scrolls inside: the panel's maxHeight is the --factory-drop-max variable", async () => {
        render()
        await click(chip('running'))
        expect(q('[data-dropdown]')?.style.maxHeight).toBe('var(--factory-drop-max)')
        expect(q('[data-dropdown]')?.className).toContain('overflow-y-auto')
    })

    it('a pointerdown outside slides it up and clears the selection, one inside does not', async () => {
        const onSelect = vi.fn()
        render({ onSelect })
        await click(chip('running'))
        await act(async () => { q('[data-dropdown]')!.dispatchEvent(new Event('pointerdown', { bubbles: true })) })
        expect(q('[data-dropdown]')).not.toBeNull()
        expect(onSelect).not.toHaveBeenCalled()
        await act(async () => { document.body.dispatchEvent(new Event('pointerdown', { bubbles: true })) })
        expect(q('[data-dropdown]')).toBeNull()
        expect(onSelect).toHaveBeenCalledWith(null)
    })

    it('an opened bucket drops the list of its jobs down, a row asks for the card, and a press outside or on a chip leaves the bucket', async () => {
        const onSelect = vi.fn()
        const onBucket = vi.fn()
        const s = snapshot()
        render({ bucket: 'rejects', onSelect, onBucket, snapshot: { ...s, jobs: [...s.jobs, job(15, { state: 'rejected', reason: 'tests missing' })] } })
        expect(q('[data-bucket-row="15"]')!.textContent).toContain('tests missing')
        expect(q('[data-task="11"]')).toBeNull()
        await click(q('[data-bucket-open="15"]'))
        expect(onSelect).toHaveBeenCalledWith(15)
        await click(chip('running'))
        expect(onBucket).toHaveBeenLastCalledWith(null)
        onBucket.mockClear()
        await act(async () => { document.body.dispatchEvent(new Event('pointerdown', { bubbles: true })) })
        expect(onBucket).toHaveBeenCalledWith(null)
    })

    it('while paused shows one paused indicator, and drops the no-data figures but keeps a zero', async () => {
        const s = snapshot()
        const paused: FactorySnapshot = {
            ...s,
            control: { state: 'PAUSED', by: 'owner', at: s.madeAt },
            holds: [{ kind: 'paused', until: new Date(Date.now() + 39_000).toISOString() }],
            jobs: s.jobs.filter(j => j.state !== 'building'),
        }
        const topBar = createElement(FactoryTopBar, { snapshot: paused, controls: { view: null, loadError: null, reload: async () => {} }, selected: null, onSelect: () => {}, names: {}, onOpenCoworker: () => {} })
        await act(async () => {
            root.render(createElement(TooltipProvider, null, createElement(FactoryWorld, { snapshot: paused, scene: (_: number, now: number) => sceneFromSnapshot(paused, now), topBar })))
        })
        const pills = host.querySelectorAll('[data-topbar] [role="status"][data-state-pill]')
        expect(pills).toHaveLength(1)
        expect(pills[0]!.textContent).toContain('Paused · builds finishing')
        expect(q('[data-run-now]')).toBeNull()
        expect(host.textContent).not.toContain('Line held')
        const strip = host.querySelector('[data-bar-frame="bottom"]')!
        expect(strip.textContent).not.toContain('—')
        expect(strip.querySelector('[data-metric-group="flow"]')!.textContent).toContain('0Building')
        expect(strip.querySelector('[data-metric-group="cost"]')).toBeNull()
        expect(strip.querySelector('[data-no-data]')).not.toBeNull()
    })

    it('running with no project names why nothing starts, and its action opens Projects', async () => {
        const s = snapshot()
        const idle: FactorySnapshot = {
            ...s,
            control: { state: 'RUNNING', by: 'owner', at: s.madeAt },
            holds: [{ kind: 'no work', until: new Date(Date.now() + 60_000).toISOString() }],
            work_order: { id: null, repo: null, kind: null, issues: [], text: null, by: 'owner', at: s.madeAt, current: null, done: [], skipped: [], halted: null, wait: 'no project chosen' },
        }
        await act(async () => {
            root.render(createElement(TooltipProvider, null, createElement(FactoryTopBar, {
                snapshot: idle, selected: null, onSelect: () => {}, names: {}, onOpenCoworker: () => {},
                controls: { view: { isOwner: true, activeRepo: null, state: 'RUNNING', providersOff: [], throttle: null, orders: [], projectLimits: null }, loadError: null, reload: async () => {} },
            })))
        })
        const pill = q('[data-topbar] [role="status"][data-state-pill]')!
        expect(pill.textContent).toContain('Running, nothing to work on: no project chosen')
        expect(pill.textContent).toContain('No work · no project chosen')
        const start = q('[data-state-button="RUNNING"]')!
        expect(start.getAttribute('aria-disabled')).toBe('true')
        expect(start.getAttribute('aria-label')).toBe('Start: pick a project first')
        const projects = q('[data-project-picker] > button')!
        expect(projects.getAttribute('aria-expanded')).toBe('false')
        await click(q('[data-needs-project]'))
        expect(projects.getAttribute('aria-expanded')).toBe('true')
        await click(projects)
        expect(projects.getAttribute('aria-expanded')).toBe('false')
        await click(q('[data-pill-action="project"]'))
        expect(q('[data-pill-action="project"]')!.textContent).toBe('Projects')
        expect(projects.getAttribute('aria-expanded')).toBe('true')
    })

    it('with a project but no work order, Start waits for the work and the primary Choose the work opens it', async () => {
        const s = snapshot()
        const idle: FactorySnapshot = {
            ...s,
            control: { state: 'RUNNING', by: 'owner', at: s.madeAt },
            holds: [{ kind: 'no work', until: new Date(Date.now() + 60_000).toISOString() }],
            work_order: { id: null, repo: 'o/r', kind: null, issues: [], text: null, by: 'owner', at: s.madeAt, current: null, done: [], skipped: [], halted: null, wait: 'no work order' },
        }
        await act(async () => {
            root.render(createElement(TooltipProvider, null, createElement(FactoryTopBar, {
                snapshot: idle, selected: null, onSelect: () => {}, names: {}, onOpenCoworker: () => {},
                controls: { view: { isOwner: true, activeRepo: 'o/r', state: 'RUNNING', providersOff: [], throttle: null, orders: [], projectLimits: null }, loadError: null, reload: async () => {} },
            })))
        })
        const start = q('[data-state-button="RUNNING"]')!
        expect(start.getAttribute('aria-disabled')).toBe('true')
        expect(start.getAttribute('aria-label')).toBe('Start: choose the work first')
        expect(q('[data-state-button="PAUSED"]')!.hasAttribute('aria-disabled')).toBe(false)
        const trigger = q('[data-order-trigger="ask"]')!
        expect(trigger.className).toContain('bg-primary')
        expect(trigger.getAttribute('aria-expanded')).toBe('false')
        expect(q('[data-state-pill]')!.textContent).toContain('No work · no work order')
        await click(q('[data-pill-action="order"]'))
        expect(trigger.getAttribute('aria-expanded')).toBe('true')
    })

    it('after a click the pill shows the ask until the factory reports it', async () => {
        const s = snapshot()
        const at = (state: 'RUNNING' | 'STOPPED') => createElement(TooltipProvider, null, createElement(FactoryTopBar, {
            snapshot: { ...s, control: { state, by: 'owner', at: s.madeAt } }, selected: null, onSelect: () => {}, names: {}, onOpenCoworker: () => {},
            controls: { view: { isOwner: true, activeRepo: 'o/r', state: 'STOPPED', providersOff: [], throttle: null, orders: [], projectLimits: null }, loadError: null, reload: async () => {} },
        }))
        await act(async () => { root.render(at('RUNNING')) })
        const pill = q('[data-state-pill]')!
        expect(pill.getAttribute('data-state-pill')).toBe('asked')
        expect(pill.textContent).toContain('Asked for stopped: waiting for the factory')
        expect(pill.querySelector('.animate-pulse')).not.toBeNull()
        await act(async () => { root.render(at('STOPPED')) })
        expect(q('[data-state-pill]')!.getAttribute('data-state-pill')).toBe('STOPPED')
        expect(q('[data-state-pill]')!.querySelector('.animate-pulse')).toBeNull()
    })

    it('with no snapshot says it is the sample and has no chips', () => {
        render({ snapshot: null })
        expect(host.textContent).toContain(SAMPLE_TEXT)
        expect(q('[data-chip]')).toBeNull()
    })
})
