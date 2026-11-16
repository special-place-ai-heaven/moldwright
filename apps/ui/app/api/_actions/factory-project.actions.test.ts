import { beforeEach, describe, expect, it, vi } from 'vitest'

import { factoryProjectsSchema } from '@rerun/contracts'

import type { ProjectInsert, ProjectRow } from '@/lib/factory/projects'

const mocks = vi.hoisted(() => ({ context: vi.fn(), rows: [] as Array<Record<string, unknown>>, owner: 'user-rob' as string | null }))

vi.mock('server-only', () => ({}))
vi.mock('@/app/api/_auth/ownership', () => ({ requireWorkspaceContext: mocks.context, requireWorkspaceId: vi.fn(async () => 7) }))
vi.mock('@/lib/factory/projects', async original => ({
    ...(await original<typeof import('@/lib/factory/projects')>()),
    projectRows: () => ({
        list: async (workspaceId: number) => mocks.rows.filter(r => r.workspace_id === workspaceId).map(r => ({ ...r })) as ProjectRow[],
        insert: async (row: ProjectInsert) => {
            mocks.rows.push({ active: false, wanted: false, ready: false, added_at: '2026-11-16T18:00:00Z', base_branch: null, check_asked_at: null, checked_at: null, left_at: null, readiness: [], selected_at: null, selected_by: null, ...row })
        },
        update: async (workspaceId: number, repo: string, patch: Record<string, unknown>) => {
            Object.assign(mocks.rows.find(r => r.workspace_id === workspaceId && r.repo === repo) ?? {}, patch)
        },
        owner: async () => mocks.owner,
    }),
}))

const { addFactoryProjectAction, readFactoryProjectsAction, selectFactoryProjectAction } = await import('./factory.actions')

const HOME = 'special-place-ai-heaven/rerun'
const OTHER = 'special-place-ai-heaven/testpilot'
const as = (userId: string, userEmail: string | null = `${userId}@example.com`) => mocks.context.mockResolvedValue({ userId, userEmail, workspace: { id: 7 }, role: 'admin', supabase: {} })

beforeEach(() => {
    vi.clearAllMocks()
    mocks.owner = 'user-rob'
    mocks.rows.length = 0
    mocks.rows.push({ workspace_id: 7, repo: HOME, link: HOME, added_at: '2026-11-16T17:00:00Z', added_by: 'factory', active: true, wanted: false, ready: true, base_branch: 'dev', check_asked_at: null, checked_at: null, left_at: null, readiness: [], selected_at: null, selected_by: 'factory' })
})

describe('the project actions of the Factory page', () => {
    it('the owner adds a project by its git link and it is listed, not yet ready, with its check asked for', async () => {
        as('user-rob')
        expect(await addFactoryProjectAction('https://github.com/special-place-ai-heaven/testpilot.git')).toEqual({ ok: true, repo: OTHER })
        const page = await readFactoryProjectsAction()
        expect(factoryProjectsSchema.safeParse(page).success).toBe(true)
        expect(page).toMatchObject({ owner: true, ownerSet: true, active: HOME, wanted: null })
        expect(page.projects.find(p => p.repo === OTHER)).toMatchObject({ addedBy: 'user-rob@example.com', ready: false, checking: true, active: false })
    })

    it('the owner selects an added project: it is wanted, not active, until its check passed', async () => {
        as('user-rob')
        await addFactoryProjectAction(OTHER)
        expect(await selectFactoryProjectAction(OTHER)).toEqual({ ok: true, repo: OTHER })
        expect(await readFactoryProjectsAction()).toMatchObject({ active: HOME, wanted: OTHER })
        expect(mocks.rows.find(r => r.repo === OTHER)).toMatchObject({ selected_by: 'user-rob@example.com', active: false })
    })

    it('an admin who is not the owner changes nothing and still reads which project the factory works on', async () => {
        as('user-colleague')
        expect(await addFactoryProjectAction(OTHER)).toEqual({ ok: false, reason: 'owner' })
        expect(await selectFactoryProjectAction(HOME)).toEqual({ ok: false, reason: 'owner' })
        expect(mocks.rows).toHaveLength(1)
        expect(await readFactoryProjectsAction()).toMatchObject({ owner: false, ownerSet: true, active: HOME })
    })

    it('with no owner set nobody changes anything and the page is told so', async () => {
        mocks.owner = null
        as('user-rob')
        expect(await addFactoryProjectAction(OTHER)).toEqual({ ok: false, reason: 'owner' })
        expect(await readFactoryProjectsAction()).toMatchObject({ owner: false, ownerSet: false })
    })

    it('a refused link, an unknown project and the active one each answer their reason', async () => {
        as('user-rob')
        expect(await addFactoryProjectAction('https://gitlab.com/a/b')).toEqual({ ok: false, reason: 'link' })
        expect(await addFactoryProjectAction(undefined as unknown as string)).toEqual({ ok: false, reason: 'link' })
        expect(await selectFactoryProjectAction('special-place-ai-heaven/never-added')).toEqual({ ok: false, reason: 'unknown' })
        expect(await selectFactoryProjectAction(HOME)).toEqual({ ok: false, reason: 'active' })
    })

    it('a signed-in user without an email is named by id', async () => {
        as('user-rob', null)
        await addFactoryProjectAction(OTHER)
        expect(mocks.rows.find(r => r.repo === OTHER)?.added_by).toBe('user-rob')
    })

    it('someone who is not signed in to the workspace gets the refusal of the session, not a list', async () => {
        mocks.context.mockRejectedValue(new Error('notAMember'))
        await expect(readFactoryProjectsAction()).rejects.toThrow('notAMember')
        await expect(addFactoryProjectAction(OTHER)).rejects.toThrow('notAMember')
    })
})
