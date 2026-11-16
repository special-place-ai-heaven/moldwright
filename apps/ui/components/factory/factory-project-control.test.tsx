// @vitest-environment happy-dom
import { readFileSync } from 'node:fs'
import path from 'node:path'
import { act, createElement } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { factoryProjectsSchema, factorySnapshotSchema, type FactoryProjects, type FactorySnapshot } from '@rerun/contracts'

import { FactoryProject } from './FactoryProject'
import { confirmText, snapshotFits, type ProjectsState } from './factory-project'

const ROOT = path.resolve(import.meta.dirname, '../../../..')
const read = (name: string) => JSON.parse(readFileSync(path.join(ROOT, 'packages/contracts/fixtures', name), 'utf8'))
const HOME = 'special-place-ai-heaven/rerun'
const OTHER = 'special-place-ai-heaven/testpilot'
const snapshot = (over: Partial<FactorySnapshot> = {}): FactorySnapshot => factorySnapshotSchema.parse({ ...read('factory-snapshot.sample.json'), home: HOME, ...over })
const list = (over: Partial<FactoryProjects> = {}): FactoryProjects => {
    const base = factoryProjectsSchema.parse(read('factory-project.sample.json').projects)
    const projects = base.projects.map(p => ({ ...p, active: p.repo === HOME, leftAt: null, selectedAt: null }))
    return { ...base, active: HOME, previous: null, projects, ...over }
}

let host: HTMLDivElement
let root: Root
const q = (s: string) => host.querySelector(s) as HTMLElement | null
const all = (s: string) => Array.from(host.querySelectorAll<HTMLElement>(s))
const click = (el: Element | null) => act(async () => { el!.dispatchEvent(new MouseEvent('click', { bubbles: true })); await Promise.resolve() })
const type = (el: HTMLInputElement, value: string) => act(() => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value')!.set!.call(el, value)
    el.dispatchEvent(new Event('input', { bubbles: true }))
})
const onAdd = vi.fn()
const onSelect = vi.fn()
const render = (projects: ProjectsState, snap: FactorySnapshot | null = snapshot()) => act(() => {
    root.render(createElement(FactoryProject, { projects, snapshot: snap, onAdd, onSelect }))
})
const opened = async (projects: ProjectsState, snap: FactorySnapshot | null = snapshot()) => {
    render(projects, snap)
    if (!q('[data-project-panel]')) await click(q('[data-project-toggle]'))
}

beforeEach(() => {
    host = document.createElement('div')
    document.body.appendChild(host)
    root = createRoot(host)
    ;(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true
    onAdd.mockReset().mockResolvedValue({ ok: true, repo: OTHER })
    onSelect.mockReset().mockResolvedValue({ ok: true, repo: OTHER })
})
afterEach(() => { act(() => root.unmount()); host.remove() })

describe('the project control of the Factory page', () => {
    it('closed, it shows the project the factory works on and nothing else', () => {
        render(list())
        expect(q('[data-project-active]')?.textContent).toBe(HOME)
        expect(q('[data-project-panel]')).toBeNull()
        expect(host.querySelectorAll('[data-chip]')).toHaveLength(0)
    })

    it('opens on a click and closes on Close, and lists each project with its state, base and every readiness line', async () => {
        await opened(list())
        expect(all('[data-project-row]').map(r => r.dataset.projectRow)).toEqual([HOME, OTHER])
        expect(all('[data-project-state]').map(s => s.textContent)).toEqual(['active', 'ready'])
        expect(q(`[data-project-row="${OTHER}"]`)?.textContent).toContain('base main')
        expect(q(`[data-project-row="${OTHER}"]`)?.querySelectorAll('[data-project-line]')).toHaveLength(9)
        await click(q('[data-project-close]'))
        expect(q('[data-project-panel]')).toBeNull()
    })

    it('selecting asks once, names the repository and the jobs in flight, and does nothing on Cancel', async () => {
        const snap = snapshot()
        const inFlight = snap.jobs.filter(j => !['merged', 'rejected', 'blocked', 'failed', 'returned', 'superseded', 'waiting'].includes(j.state)).length
        await opened(list(), snap)
        await click(q(`[data-project-row="${OTHER}"] [data-project-select]`))
        expect(q('[data-project-confirm]')?.textContent).toContain(confirmText(OTHER, HOME, inFlight))
        expect(confirmText(OTHER, HOME, 3)).toBe(`Work on ${OTHER}? Its readiness is checked again first. New jobs then come only from ${OTHER}. The 3 jobs in flight of ${HOME} finish their path (build, review, proof, merge); nothing is cancelled.`)
        await click(q('[data-project-no]'))
        expect(q('[data-project-confirm]')).toBeNull()
        expect(onSelect).not.toHaveBeenCalled()
        await click(q(`[data-project-row="${OTHER}"] [data-project-select]`))
        await click(q('[data-project-yes]'))
        expect(onSelect).toHaveBeenCalledTimes(1)
        expect(onSelect).toHaveBeenCalledWith(OTHER)
        expect(q('[data-project-answer]')?.textContent).toBe(`Checking the readiness of ${OTHER}. It becomes the project when every line passes.`)
    })

    it('a project that is not ready cannot be selected and its failed line is on the page', async () => {
        const projects = list()
        projects.projects[1] = { ...projects.projects[1], ready: false, lines: [{ name: 'checks', ok: false, text: 'no check has ever run on a pull request: the line merges nothing untested' }] }
        await opened(projects)
        expect((q(`[data-project-row="${OTHER}"] [data-project-select]`) as HTMLButtonElement).disabled).toBe(true)
        expect(q('[data-project-line="failed"]')?.textContent).toContain('no check has ever run on a pull request')
        expect(all('[data-project-state]')[1].textContent).toBe('not ready')
    })

    it('adding sends the link as typed and shows what happened; a refused link says how to write one', async () => {
        await opened(list())
        const input = q('[data-project-link]') as HTMLInputElement
        expect((q('[data-project-add-button]') as HTMLButtonElement).disabled).toBe(true)
        type(input, 'https://github.com/special-place-ai-heaven/testpilot.git')
        await click(q('[data-project-add-button]'))
        expect(onAdd).toHaveBeenCalledWith('https://github.com/special-place-ai-heaven/testpilot.git')
        expect(q('[data-project-answer]')?.textContent).toBe(`Added ${OTHER}. Its readiness is being checked.`)
        onAdd.mockResolvedValue({ ok: false, reason: 'link' })
        type(q('[data-project-link]') as HTMLInputElement, 'nonsense')
        await click(q('[data-project-add-button]'))
        expect(q('[data-project-answer]')?.textContent).toBe('Not a git link. Write https://github.com/<owner>/<repo> or <owner>/<repo>.')
    })

    it('someone who is not the owner sees the project and the list with every control disabled and the reason', async () => {
        await opened(list({ owner: false }))
        expect(q('[data-project-active]')?.textContent).toBe(HOME)
        expect(q('[data-project-readonly]')?.textContent).toBe('Only the factory owner changes the project.')
        expect(all('button[data-project-select], [data-project-add-button], [data-project-link]').every(e => (e as HTMLButtonElement).disabled)).toBe(true)
        await opened(list({ owner: false, ownerSet: false }))
        expect(q('[data-project-readonly]')?.textContent).toBe('No factory owner is set for this workspace.')
    })

    it('shows loading, empty, refused and unreachable each as what it is', async () => {
        await opened('loading', null)
        expect([q('[data-project]')?.dataset.state, q('[data-project-active]')?.textContent, q('[data-project-note]')?.textContent]).toEqual(['loading', 'loading', 'Loading the projects.'])
        await opened('unreachable')
        expect(q('[data-project]')?.dataset.state).toBe('unreachable')
        expect(q('[data-project-note]')?.textContent).toBe(`The list of projects cannot be read right now. The factory keeps the project it knew: ${HOME}.`)
        await opened(list({ active: null, projects: [] }))
        expect(q('[data-project]')?.dataset.state).toBe('empty')
        expect(q('[data-project-note]')?.textContent).toBe(`No project is added yet. The factory works on its home, ${HOME}.`)
        onAdd.mockResolvedValue({ ok: false, reason: 'owner' })
        await opened(list())
        type(q('[data-project-link]') as HTMLInputElement, OTHER)
        await click(q('[data-project-add-button]'))
        expect(q('[data-project-answer]')?.textContent).toBe('Refused: only the factory owner changes the project.')
        onAdd.mockRejectedValue(new Error('network'))
        type(q('[data-project-link]') as HTMLInputElement, OTHER)
        await click(q('[data-project-add-button]'))
        expect(q('[data-project-answer]')?.textContent).toBe('The app did not answer. Nothing was changed.')
    })

    it('shows what is finishing, the last switch with who and when, and one click goes back to the project before', async () => {
        const snap = snapshot({ repo: OTHER, ...read('factory-project.sample.json').snapshot })
        const projects = factoryProjectsSchema.parse(read('factory-project.sample.json').projects)
        await opened(projects, snap)
        expect(all('[data-project-finishing]').map(e => e.textContent)).toEqual([`finishing 2 jobs of ${HOME}`])
        expect(q('[data-project-switch]')?.textContent).toBe(`Last switch: ${HOME} to ${OTHER}, by rob@example.com at 2026-11-16T18:00:00Z.`)
        await click(q('[data-project-back]'))
        expect(onSelect).toHaveBeenCalledWith(HOME)
        expect(q('[data-project-confirm]')).toBeNull()
    })

    it('a picture is drawn only when it is of the active project, of the one before, or the active one is still finishing in it', () => {
        const projects = list({ active: OTHER, previous: HOME })
        expect(snapshotFits(projects, snapshot({ repo: OTHER }))).toBe(true)
        expect(snapshotFits(projects, snapshot({ repo: HOME }))).toBe(true)
        expect(snapshotFits(projects, snapshot({ repo: 'special-place-ai-heaven/terminal-commander' }))).toBe(false)
        expect(snapshotFits(projects, snapshot({ repo: 'special-place-ai-heaven/terminal-commander', finishing: [{ repo: OTHER, jobs: 1 }] }))).toBe(true)
        expect(snapshotFits(list({ active: null, projects: [] }), snapshot({ repo: OTHER }))).toBe(false)
        expect(snapshotFits(list({ active: null, projects: [] }), snapshot({ repo: HOME }))).toBe(true)
        expect(snapshotFits('unreachable', snapshot({ repo: OTHER }))).toBe(true)
        expect(snapshotFits(projects, null)).toBe(true)
    })
})
