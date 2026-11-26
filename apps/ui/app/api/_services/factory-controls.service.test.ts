import { beforeEach, describe, expect, it, vi } from 'vitest'

import { workspaceFounderUserId } from '@/app/api/_auth/ownership'
import { putFactorySnapshot } from '@/lib/factory/snapshot-store'
import { createServiceRoleClient } from '@/supabase/serviceRole'
import { selectMany, selectMaybeSingle } from '@/supabase/supabase-helpers'

import { FACTORY_WIRE_ID_PATTERN, type FactorySnapshot } from '@moldwright/contracts'

import { actOnWorkOrder, cancelWorkOrder, clearFactoryQueue, controlsReportAnswer, createWorkOrder, setFactoryState, setFactoryThrottle, setProviderEnabled } from './factory-controls.service'

vi.mock('server-only', () => ({}))
vi.mock('@/app/api/_auth/ownership', () => ({ workspaceFounderUserId: vi.fn() }))
vi.mock('@/supabase/serviceRole', () => ({ createServiceRoleClient: vi.fn() }))
vi.mock('@/supabase/supabase-helpers', () => ({ selectMaybeSingle: vi.fn(), selectMany: vi.fn() }))

const OWNER = 'owner-1'
const MEMBER = 'member-2'
const upsert = vi.fn()
const insert = vi.fn()
const update = vi.fn()
const from = vi.fn()
const cas = { eq: vi.fn(), is: vi.fn(), select: vi.fn() }

type Rows = { factory_projects?: object | null; factory_controls?: object | null; workspace_members?: object | null }
function rows(by: Rows, orders: object[] = []) {
    vi.mocked(selectMaybeSingle).mockImplementation((async (_client: unknown, table: keyof Rows) => ({ data: table === 'workspace_members' ? { role: 'admin' } : by[table] ?? null, error: null })) as never)
    vi.mocked(selectMany).mockResolvedValue({ data: orders, error: null } as never)
}

beforeEach(() => {
    vi.clearAllMocks()
    vi.mocked(workspaceFounderUserId).mockResolvedValue(OWNER)
    upsert.mockResolvedValue({ error: null })
    insert.mockResolvedValue({ error: null })
    cas.eq.mockReturnValue(cas)
    cas.is.mockReturnValue(cas)
    cas.select.mockResolvedValue({ data: [{ workspace_id: 0 }], error: null })
    update.mockReturnValue(cas)
    from.mockReturnValue({ upsert, insert, update })
    vi.mocked(createServiceRoleClient).mockReturnValue({ from } as never)
})

describe('factory controls: owner only', () => {
    it('refuses state, provider and work-order changes to a member who is not the workspace owner, and reads or writes nothing', async () => {
        const refused = { code: 'factoryOwnerOnly', name: 'AuthorizationError' }
        await expect(setFactoryState(401, MEMBER, 'RUNNING')).rejects.toMatchObject(refused)
        await expect(setFactoryState(401, MEMBER, 'STOPPED')).rejects.toMatchObject(refused)
        await expect(setProviderEnabled(401, MEMBER, 'conn-a', false)).rejects.toMatchObject(refused)
        await expect(createWorkOrder(401, MEMBER, { repo: 'acme/app', kind: 'issue', issues: [12], text: '' })).rejects.toMatchObject(refused)
        await expect(cancelWorkOrder(401, MEMBER, 'order-1')).rejects.toMatchObject(refused)
        await expect(actOnWorkOrder(401, MEMBER, 'order-1', 'retry', 12)).rejects.toMatchObject(refused)
        expect(from).not.toHaveBeenCalled()
        expect(selectMaybeSingle).not.toHaveBeenCalled()
    })

    it('refuses a work order for a project that is not the active one, and inserts nothing', async () => {
        rows({ factory_projects: { repo: 'acme/app' } })
        await expect(createWorkOrder(402, OWNER, { repo: 'acme/site', kind: 'issue', issues: [7], text: '' })).rejects.toMatchObject({ code: 'factoryOrderNotActiveProject', params: { repo: 'acme/site' } })
        expect(insert).not.toHaveBeenCalled()
        expect(from).not.toHaveBeenCalled()
    })
})

describe('factory_report answer for controls', () => {
    it('sends nothing for a brand-new workspace, then the stored click with a fresh at each time, the off-list and the active order of the active project', async () => {
        rows({})
        expect(await controlsReportAnswer(403)).toEqual({})

        await setFactoryState(403, OWNER, 'RUNNING', Date.parse('2026-11-23T20:00:00.100Z'))
        await setFactoryState(403, OWNER, 'RUNNING', Date.parse('2026-11-23T20:00:00.900Z'))
        const clicks = upsert.mock.calls.map(([payload]) => payload.state_at)
        expect(clicks).toEqual(['2026-11-23T20:00:00.100Z', '2026-11-23T20:00:00.900Z'])

        rows({
            factory_projects: { repo: 'acme/app' },
            factory_controls: { state: 'RUNNING', state_by: OWNER, state_at: '2026-11-23T20:00:00.900+00:00', providers_off: ['conn-b'], providers_by: OWNER, providers_at: '2026-11-23T19:59:00+00:00' },
        }, [{ id: 'order-1', repo: 'acme/app', kind: 'all_issues', issues: [3, 1, 2], text: '', status: 'active', action: { action: 'skip', issue: 1, by: OWNER, at: '2026-11-23T20:05:00.000Z' }, created_by: OWNER, created_at: '2026-11-23T20:01:00+00:00', cancelled_by: null, cancelled_at: null }])
        expect(await controlsReportAnswer(403)).toEqual({
            control: { state: 'RUNNING', by: OWNER, at: '2026-11-23T20:00:00.900Z' },
            providers: { off: ['conn-b'], by: OWNER, at: '2026-11-23T19:59:00.000Z' },
            work_order: { id: 'order-1', repo: 'acme/app', kind: 'all_issues', issues: [3, 1, 2], text: '', by: OWNER, at: '2026-11-23T20:01:00.000Z' },
            work_order_action: { action: 'skip', order_id: 'order-1', issue: 1, by: OWNER, at: '2026-11-23T20:05:00.000Z' },
        })
        expect(selectMany).toHaveBeenCalledWith(expect.anything(), 'factory_work_orders', expect.anything(), { workspace_id: 403, repo: 'acme/app' }, { column: 'created_at', ascending: false }, 1)
    })

    it('refuses the pool and seats to a member, sends no throttle before the first set, then the stored pool and seats with a fresh at each time', async () => {
        const refused = { code: 'factoryOwnerOnly', name: 'AuthorizationError' }
        await expect(setFactoryThrottle(404, MEMBER, { maxGhosts: 16 })).rejects.toMatchObject(refused)
        await expect(setFactoryThrottle(404, MEMBER, { station: 'coder', seats: 5 })).rejects.toMatchObject(refused)
        expect(from).not.toHaveBeenCalled()

        rows({ factory_controls: { state: 'RUNNING', state_by: OWNER, state_at: '2026-11-23T20:00:00+00:00', providers_off: [], providers_by: null, providers_at: null, max_ghosts: 1, stations: {}, throttle_by: null, throttle_at: null } })
        expect(await controlsReportAnswer(404)).not.toHaveProperty('throttle')

        await expect(setFactoryThrottle(404, OWNER, { maxGhosts: 33 })).rejects.toMatchObject({ code: 'factoryInputInvalid' })
        await setFactoryThrottle(404, OWNER, { maxGhosts: 16 }, Date.parse('2026-11-23T21:00:00.100Z'))
        await setFactoryThrottle(404, OWNER, { maxGhosts: 16 }, Date.parse('2026-11-23T21:00:00.900Z'))
        expect(upsert.mock.calls.map(([payload]) => [payload.max_ghosts, payload.throttle_at])).toEqual([[16, '2026-11-23T21:00:00.100Z'], [16, '2026-11-23T21:00:00.900Z']])

        rows({ factory_controls: { state: null, state_by: null, state_at: null, providers_off: [], providers_by: null, providers_at: null, max_ghosts: 16, stations: { coder: 5, reviewer: 6 }, throttle_by: OWNER, throttle_at: '2026-11-23T21:00:00.900+00:00' } })
        expect(await controlsReportAnswer(404)).toEqual({ throttle: { max_ghosts: 16, stations: { coder: 5, reviewer: 6 }, by: OWNER, at: '2026-11-23T21:00:00.900Z' } })
    })
})

describe('factory queue clear', () => {
    it('refuses a member, a bad or duplicate issue list and another project, then sends the dispatcher the confirmed issues under a wire id', async () => {
        await expect(clearFactoryQueue(405, MEMBER, { repo: 'acme/app', issues: [4] })).rejects.toMatchObject({ code: 'factoryOwnerOnly' })
        rows({ factory_projects: { repo: 'acme/app' } })
        for (const issues of [[], [4, 4], [0], [1.5]]) await expect(clearFactoryQueue(405, OWNER, { repo: 'acme/app', issues })).rejects.toMatchObject({ code: 'factoryInputInvalid' })
        await expect(clearFactoryQueue(405, OWNER, { repo: 'acme/site', issues: [4] })).rejects.toMatchObject({ code: 'factoryOrderNotActiveProject' })
        expect(insert).not.toHaveBeenCalled()

        const sent = await clearFactoryQueue(405, OWNER, { repo: 'acme/app', issues: [4, 9] }, Date.parse('2026-11-25T09:00:00.500Z'))
        expect(sent).toEqual({ id: expect.stringMatching(FACTORY_WIRE_ID_PATTERN), count: 2 })
        const [payload] = insert.mock.calls[0]
        rows({ factory_controls: { ...payload, queue_clear_at: '2026-11-25T09:00:00.500+00:00' } })
        expect(await controlsReportAnswer(405)).toEqual({ queue_clear: { id: sent.id, repo: 'acme/app', issues: [4, 9], by: OWNER, at: '2026-11-25T09:00:00.500Z' } })
    })

    it('never replaces an outstanding clear: a second or racing submit is refused as busy until the dispatcher answers or the wait runs out', async () => {
        const at = '2026-11-25T10:00:00.000+00:00'
        const start = Date.parse(at)
        const outstanding = { queue_clear: { id: 'qc-old', repo: 'acme/app', issues: [4] }, queue_clear_by: OWNER, queue_clear_at: at }
        const busy = { code: 'factoryQueueClearBusy' }
        rows({ factory_projects: { repo: 'acme/app' } })
        insert.mockResolvedValueOnce({ error: null }).mockResolvedValueOnce({ error: { code: '23505' } })
        const raced = await Promise.allSettled([clearFactoryQueue(406, OWNER, { repo: 'acme/app', issues: [4] }, start), clearFactoryQueue(406, OWNER, { repo: 'acme/app', issues: [9] }, start)])
        expect(raced.map(r => r.status)).toEqual(['fulfilled', 'rejected'])
        expect(raced[1]).toMatchObject({ reason: busy })

        rows({ factory_projects: { repo: 'acme/app' }, factory_controls: outstanding })
        await expect(clearFactoryQueue(406, OWNER, { repo: 'acme/app', issues: [9] }, start + 179_000)).rejects.toMatchObject(busy)
        expect(update).not.toHaveBeenCalled()

        putFactorySnapshot(406, { madeAt: '2026-11-25T10:00:30.000Z', queue_clear: { id: 'qc-old', repo: 'acme/app', outcome: 'expired', cleared: [], kept: [], at } } as unknown as FactorySnapshot)
        cas.select.mockResolvedValueOnce({ data: [{ workspace_id: 406 }], error: null }).mockResolvedValueOnce({ data: [], error: null })
        const retried = await Promise.allSettled([clearFactoryQueue(406, OWNER, { repo: 'acme/app', issues: [9] }, start + 40_000), clearFactoryQueue(406, OWNER, { repo: 'acme/app', issues: [4] }, start + 40_000)])
        expect(raced.length + retried.filter(r => r.status === 'fulfilled').length).toBe(3)
        expect(retried[1]).toMatchObject({ reason: busy })
        expect(cas.eq).toHaveBeenCalledWith('queue_clear_at', at)
        expect(update.mock.calls[0][0]).toMatchObject({ queue_clear: { repo: 'acme/app', issues: [9] }, queue_clear_at: '2026-11-25T10:00:40.000Z' })

        rows({ factory_projects: { repo: 'acme/app' }, factory_controls: { ...outstanding, queue_clear: { ...outstanding.queue_clear, id: 'qc-unanswered' } } })
        await expect(clearFactoryQueue(406, OWNER, { repo: 'acme/app', issues: [4] }, start + 180_000)).resolves.toMatchObject({ count: 1 })
    })
})
