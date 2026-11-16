import { readFileSync } from 'node:fs'
import path from 'node:path'
import { describe, expect, it, vi } from 'vitest'

import { factoryProjectsSchema, factoryReportAnswerSchema, factorySnapshotSchema, type FactorySnapshot } from '@rerun/contracts'

import { addFactoryProject, listFactoryProjects, selectFactoryProject, takeFactoryReport, type ProjectInsert, type ProjectRow, type ProjectRows } from './projects'

vi.mock('server-only', () => ({}))

const ROOT = path.resolve(import.meta.dirname, '../../../..')
const SAMPLE = JSON.parse(readFileSync(path.join(ROOT, 'packages/contracts/fixtures/factory-project.sample.json'), 'utf8'))
const HOME = 'special-place-ai-heaven/rerun'
const OTHER = 'special-place-ai-heaven/testpilot'
const WS = 7
const at = (seconds: number) => new Date(Date.UTC(2026, 10, 16, 18, 0, seconds))

function memory(): ProjectRows & { rows: ProjectRow[]; writes: number } {
    const store = {
        rows: [] as ProjectRow[],
        writes: 0,
        async owner() {
            return 'user-rob'
        },
        async list(workspaceId: number) {
            return store.rows.filter(r => r.workspace_id === workspaceId).map(r => ({ ...r }))
        },
        async insert(row: ProjectInsert) {
            store.writes += 1
            if (store.rows.some(r => r.workspace_id === row.workspace_id && r.repo === row.repo)) throw new Error('duplicate key')
            store.rows.push({
                active: false, wanted: false, ready: false, added_at: at(0).toISOString(), base_branch: null, check_asked_at: null, checked_at: null,
                left_at: null, readiness: [], selected_at: null, selected_by: null, ...row,
            } as ProjectRow)
        },
        async update(workspaceId: number, repo: string, patch: Partial<ProjectRow>) {
            store.writes += 1
            const row = store.rows.find(r => r.workspace_id === workspaceId && r.repo === repo)
            if (row) Object.assign(row, patch)
            if (store.rows.filter(r => r.workspace_id === workspaceId && r.active).length > 1) throw new Error('two active projects')
        },
    }
    return store
}

const snap = (extra: Partial<FactorySnapshot> = {}): FactorySnapshot => factorySnapshotSchema.parse({
    version: 1, madeAt: '2026-11-16T18:00:00Z', beat: 1, repo: HOME, home: HOME, jobs: [], holds: [], pools: [],
    endedToday: { merged: 0, rejected: 0, blocked: 0, failed: 0, returned: 0 }, ...extra,
})
const result = (repo: string, seconds: number, passed = true) => ({ ...SAMPLE.snapshot.readiness[0], repo, at: at(seconds).toISOString().replace('.000Z', 'Z'), passed })
const row = (db: ReturnType<typeof memory>, repo: string) => db.rows.find(r => r.repo === repo)!

describe('the projects of a workspace', () => {
    it('with nothing chosen the home becomes the one project, active, and its readiness is asked for', async () => {
        const db = memory()
        const answer = await takeFactoryReport(db, WS, snap(), at(0))
        expect(answer).toEqual({ project: { repo: HOME, by: 'factory' }, check: [HOME] })
        expect(factoryReportAnswerSchema.safeParse({ kept: true, ...answer }).success).toBe(true)
        expect(await takeFactoryReport(db, WS, snap(), at(30))).toEqual(answer)
        expect(db.rows).toHaveLength(1)
    })

    it('a picture from a dispatcher that names no home changes nothing and answers no project', async () => {
        const db = memory()
        expect(await takeFactoryReport(db, WS, snap({ home: undefined }), at(0))).toEqual({ project: null, check: [] })
        expect(db.writes).toBe(0)
    })

    it('adding takes a git link in each form, asks for the check, and refuses anything else', async () => {
        const db = memory()
        expect(await addFactoryProject(db, WS, ' https://github.com/special-place-ai-heaven/testpilot.git ', 'rob@example.com', at(1))).toEqual({ ok: true, repo: OTHER })
        expect(row(db, OTHER)).toMatchObject({ link: 'https://github.com/special-place-ai-heaven/testpilot.git', added_by: 'rob@example.com', active: false, ready: false, check_asked_at: at(1).toISOString() })
        expect(await addFactoryProject(db, WS, 'not a link', 'rob', at(2))).toEqual({ ok: false, reason: 'link' })
        expect(await addFactoryProject(db, WS, OTHER, 'rob', at(3))).toEqual({ ok: true, repo: OTHER })
        expect(db.rows).toHaveLength(1)
        expect(row(db, OTHER).check_asked_at).toBe(at(3).toISOString())
        for (let i = 0; i < 49; i += 1) await addFactoryProject(db, WS, `special-place-ai-heaven/r${i}`, 'rob', at(4))
        expect(await addFactoryProject(db, WS, 'special-place-ai-heaven/one-too-many', 'rob', at(5))).toEqual({ ok: false, reason: 'full' })
    })

    it('a readiness the dispatcher reports is kept line by line, and an older one never answers a newer question', async () => {
        const db = memory()
        await takeFactoryReport(db, WS, snap(), at(0))
        await addFactoryProject(db, WS, OTHER, 'rob', at(20))
        expect((await takeFactoryReport(db, WS, snap({ readiness: [result(OTHER, 5, false)] }), at(21))).check).toContain(OTHER)
        expect(row(db, OTHER)).toMatchObject({ ready: false, checked_at: '2026-11-16T18:00:05Z' })
        expect(row(db, OTHER).check_asked_at).not.toBeNull()
        const answer = await takeFactoryReport(db, WS, snap({ readiness: [result(OTHER, 25)] }), at(30))
        expect(answer.check).not.toContain(OTHER)
        expect(row(db, OTHER)).toMatchObject({ ready: true, base_branch: 'main', check_asked_at: null })
        expect(row(db, OTHER).readiness).toHaveLength(9)
        const writes = db.writes
        await takeFactoryReport(db, WS, snap({ readiness: [result(OTHER, 25)] }), at(60))
        expect(db.writes).toBe(writes)
    })

    it('selecting asks for a fresh check first and the project becomes active only when that check passed', async () => {
        const db = memory()
        await takeFactoryReport(db, WS, snap({ readiness: [result(HOME, 0)] }), at(1))
        await addFactoryProject(db, WS, OTHER, 'rob', at(2))
        await takeFactoryReport(db, WS, snap({ readiness: [result(OTHER, 3)] }), at(4))
        expect(await selectFactoryProject(db, WS, OTHER, 'rob@example.com', at(40))).toEqual({ ok: true, repo: OTHER })
        expect((await takeFactoryReport(db, WS, snap({ readiness: [result(OTHER, 3)] }), at(41))).project).toEqual({ repo: HOME, by: 'factory' })
        const answer = await takeFactoryReport(db, WS, snap({ readiness: [result(OTHER, 45)] }), at(50))
        expect(answer).toEqual({ project: { repo: OTHER, by: 'rob@example.com' }, check: [] })
        expect(row(db, HOME)).toMatchObject({ active: false, left_at: at(50).toISOString() })
        expect(row(db, OTHER)).toMatchObject({ active: true, wanted: false, selected_at: at(50).toISOString(), selected_by: 'rob@example.com' })
        const page = await listFactoryProjects(db, WS)
        expect(page).toMatchObject({ active: OTHER, wanted: null, previous: HOME })
        expect(factoryProjectsSchema.safeParse({ owner: true, ownerSet: true, ...page }).success).toBe(true)
    })

    it('a project whose check failed is not selected and says why on its lines', async () => {
        const db = memory()
        await takeFactoryReport(db, WS, snap(), at(0))
        await addFactoryProject(db, WS, OTHER, 'rob', at(1))
        await selectFactoryProject(db, WS, OTHER, 'rob', at(2))
        const failed = { ...result(OTHER, 3, false), lines: [{ name: 'checks', ok: false, text: 'no check has ever run on a pull request: the line merges nothing untested' }] }
        const answer = await takeFactoryReport(db, WS, snap({ readiness: [failed] }), at(4))
        expect(answer.project).toEqual({ repo: HOME, by: 'factory' })
        expect(row(db, OTHER)).toMatchObject({ active: false, wanted: false, ready: false })
        expect((await listFactoryProjects(db, WS)).projects.find(p => p.repo === OTHER)?.lines[0].text).toContain('no check has ever run')
    })

    it('selecting refuses a project that was never added and the one that is active, and only one is wanted at a time', async () => {
        const db = memory()
        await takeFactoryReport(db, WS, snap(), at(0))
        expect(await selectFactoryProject(db, WS, OTHER, 'rob', at(1))).toEqual({ ok: false, reason: 'unknown' })
        expect(await selectFactoryProject(db, WS, HOME, 'rob', at(1))).toEqual({ ok: false, reason: 'active' })
        await addFactoryProject(db, WS, OTHER, 'rob', at(2))
        await addFactoryProject(db, WS, 'special-place-ai-heaven/terminal-commander', 'rob', at(2))
        await selectFactoryProject(db, WS, OTHER, 'rob', at(3))
        await selectFactoryProject(db, WS, 'special-place-ai-heaven/terminal-commander', 'rob', at(4))
        expect(db.rows.filter(r => r.wanted).map(r => r.repo)).toEqual(['special-place-ai-heaven/terminal-commander'])
    })

    it('one workspace never reads or changes the projects of another', async () => {
        const db = memory()
        await takeFactoryReport(db, WS, snap(), at(0))
        await addFactoryProject(db, 8, OTHER, 'someone', at(1))
        expect((await listFactoryProjects(db, WS)).projects.map(p => p.repo)).toEqual([HOME])
        expect(await selectFactoryProject(db, WS, OTHER, 'rob', at(2))).toEqual({ ok: false, reason: 'unknown' })
    })
})
