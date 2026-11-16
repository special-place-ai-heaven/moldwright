import { workspaceActor } from '@/app/api/_auth/access'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { factoryReportAnswerSchema } from '@rerun/contracts'

import { ACCOUNT_TOOL_DEFS } from '@/lib/mcp/account-tools'
import { createServiceRoleClient } from '@/supabase/serviceRole'

import { dispatchAccountTool } from './mcp-account.service'

vi.mock('server-only', () => ({}))
vi.mock('@/supabase/serviceRole', () => ({ createServiceRoleClient: vi.fn() }))
vi.mock('@/lib/engine/client')
vi.mock('@/lib/services/registry', () => ({ readRegistry: vi.fn(), connectorSkillOwners: () => new Map() }))
vi.mock('./workspace-engine.service', () => ({ findWorkspaceEngine: vi.fn(), getConnectionForAgent: vi.fn(), getWorkspaceConnection: vi.fn() }))
vi.mock('./agent.service', () => ({ changeAgentHandle: vi.fn(), createAgent: vi.fn(), deleteAgent: vi.fn(), duplicateAgent: vi.fn(), moveAgentToBox: vi.fn(), renameAgent: vi.fn() }))
vi.mock('./agent-setup.service', () => ({ declareService: vi.fn(), installServiceSlugs: vi.fn() }))
vi.mock('./chat.service', () => ({ ensureSessionRow: vi.fn(), resolveAgentTarget: vi.fn() }))
vi.mock('./services.service', () => ({ allocateServiceInstance: vi.fn(), listCatalogServices: vi.fn(), listInstalledServices: vi.fn(), loadManifest: vi.fn(), searchCatalogServices: vi.fn(), toAuthMethodSummaries: vi.fn(() => []), uninstallService: vi.fn() }))
vi.mock('./mcp-shares.service', () => ({ dispatchShareTool: vi.fn() }))

type Row = Record<string, unknown>

function database(rows: Row[], broken = false) {
    const fail = { data: null, error: { message: 'down' } }
    return {
        from: (table: string) => ({
            select: () => ({ eq: (_: string, id: number) => ({ order: async () => (broken ? fail : { data: rows.filter(r => r.table === table && r.workspace_id === id), error: null }) }) }),
            insert: async (row: Row) => {
                rows.push({ table, active: false, wanted: false, ready: false, check_asked_at: null, checked_at: null, readiness: [], selected_by: null, left_at: null, ...row })
                return { error: null }
            },
            update: (patch: Row) => ({ eq: (_: string, id: number) => ({ eq: async (__: string, repo: string) => {
                Object.assign(rows.find(r => r.table === table && r.workspace_id === id && r.repo === repo) ?? {}, patch)
                return { error: null }
            } }) }),
        }),
    }
}

const snap = (madeAt: string, extra: Record<string, unknown> = {}) => ({
    version: 1, madeAt, beat: 1, repo: 'a/b', jobs: [], holds: [], pools: [],
    endedToday: { merged: 0, rejected: 0, blocked: 0, failed: 0, returned: 0 }, ...extra,
})

describe('factory_report answers the project', () => {
    beforeEach(() => vi.clearAllMocks())

    it('says so in its description', () => {
        expect(ACCOUNT_TOOL_DEFS.find(t => t.name === 'factory_report')!.description).toContain('{ project, check }')
    })

    it('answers the active project and the checks asked for, from the table of the caller\'s workspace', async () => {
        const rows: Row[] = [{ table: 'factory_projects', workspace_id: 999, repo: 'x/y', active: true, selected_by: 'other' }]
        vi.mocked(createServiceRoleClient).mockReturnValue(database(rows) as never)
        const answer = await dispatchAccountTool(workspaceActor(201), 'factory_report', { snapshot: snap('2026-11-16T18:00:00Z', { home: 'a/b' }) })
        expect(answer).toEqual({ kept: true, project: { repo: 'a/b', by: 'factory' }, check: ['a/b'] })
        expect(factoryReportAnswerSchema.safeParse(answer).success).toBe(true)
        expect(rows.filter(r => r.workspace_id === 201).map(r => [r.table, r.repo, r.active])).toEqual([['factory_projects', 'a/b', true]])
    })

    it('answers only kept when the table cannot be read, so the dispatcher keeps the project it knew', async () => {
        vi.mocked(createServiceRoleClient).mockReturnValue(database([], true) as never)
        expect(await dispatchAccountTool(workspaceActor(202), 'factory_report', { snapshot: snap('2026-11-16T18:00:00Z', { home: 'a/b' }) })).toEqual({ kept: true })
    })

    it('answers only kept false for an older picture and reads no table for it', async () => {
        vi.mocked(createServiceRoleClient).mockReturnValue(database([]) as never)
        await dispatchAccountTool(workspaceActor(203), 'factory_report', { snapshot: snap('2026-11-16T18:00:00Z', { home: 'a/b' }) })
        vi.mocked(createServiceRoleClient).mockClear()
        expect(await dispatchAccountTool(workspaceActor(203), 'factory_report', { snapshot: snap('2026-11-16T17:00:00Z', { home: 'a/b' }) })).toEqual({ kept: false })
        expect(createServiceRoleClient).not.toHaveBeenCalled()
    })
})
