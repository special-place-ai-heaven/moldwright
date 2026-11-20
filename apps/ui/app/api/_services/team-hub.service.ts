import { AuthorizationError } from '@/app/api/_auth/errors'
import { COWORKER_NOT_FOUND, toVisibility, workspaceActor } from '@/app/api/_auth/access'
import { getAgent } from '@/lib/engine/client'
import { createServiceRoleClient } from '@/supabase/serviceRole'
import { selectAll, selectMaybeSingle } from '@/supabase/supabase-helpers'
import { resolveAgentTarget } from './chat.service'
import { dispatchAccountTool } from './mcp-account.service'
const TEAM_READS = {
    team_status: 'get_team_status',
    team_list_schedules: 'list_schedules',
    team_list_triggers: 'list_triggers',
    team_list_runs: 'list_runs',
    team_get_run: 'get_run',
} as const

type TeamTool = keyof typeof TEAM_READS

export function isTeamHubTool(name: string): name is TeamTool {
    return Object.hasOwn(TEAM_READS, name)
}

async function assertTeamSwitchedOn(callerAgentId: string, workspaceId: number): Promise<void> {
    const { conn, engineAgentId } = await resolveAgentTarget(callerAgentId, workspaceActor(workspaceId))
    const { config } = await getAgent(conn, engineAgentId)
    if (!config.tools.team) throw new Error('Reading other coworkers is switched off for this coworker.')
}

function withoutTriggerUrls(result: unknown): unknown {
    const { triggers } = result as { triggers: Array<Record<string, unknown>> }
    return { triggers: triggers.map(({ url: _url, ...trigger }) => trigger) }
}

async function allowedSpaceIds(callerAgentId: string, workspaceId: number): Promise<Set<string>> {
    const supabase = createServiceRoleClient()
    const [{ data: caller }, { data: spaces }] = await Promise.all([
        selectMaybeSingle(supabase, 'agents', ['space_id'] as const, { id: callerAgentId, workspace_id: workspaceId }),
        selectAll(supabase, 'spaces', ['id', 'visibility'] as const, { workspace_id: workspaceId }),
    ])
    const callerSpaceId = caller?.space_id ?? null
    const allowed = new Set<string>()
    for (const space of spaces ?? []) {
        if (toVisibility(space.visibility) === 'workspace' || space.id === callerSpaceId) allowed.add(space.id)
    }
    if (callerSpaceId) allowed.add(callerSpaceId)
    return allowed
}

async function assertTargetBoxAllowed(targetAgentId: string, workspaceId: number, allowedSpaces: Set<string>): Promise<void> {
    const { data: target } = await selectMaybeSingle(createServiceRoleClient(), 'agents', ['space_id'] as const, { id: targetAgentId, workspace_id: workspaceId })
    if (!target || !allowedSpaces.has(target.space_id)) throw new AuthorizationError(COWORKER_NOT_FOUND)
}

export async function dispatchTeamHubTool(callerAgentId: string, workspaceId: number, name: TeamTool, args: Record<string, unknown>): Promise<unknown> {
    await assertTeamSwitchedOn(callerAgentId, workspaceId)
    const allowedSpaces = await allowedSpaceIds(callerAgentId, workspaceId)
    if (name !== 'team_status') {
        const targetId = typeof args.agentId === 'string' ? args.agentId : ''
        if (targetId) await assertTargetBoxAllowed(targetId, workspaceId, allowedSpaces)
    } else {
        if (typeof args.spaceId === 'string' && args.spaceId && !allowedSpaces.has(args.spaceId)) {
            return { checkedAt: new Date().toISOString(), agents: [] }
        }
        if (typeof args.agentId === 'string' && args.agentId) {
            await assertTargetBoxAllowed(args.agentId, workspaceId, allowedSpaces)
        }
    }
    const result = await dispatchAccountTool(workspaceActor(workspaceId), TEAM_READS[name], args)
    if (name === 'team_status' && result && typeof result === 'object' && 'agents' in result && Array.isArray(result.agents)) {
        return {
            ...result,
            agents: result.agents.filter((agent: unknown) => {
                if (!agent || typeof agent !== 'object' || !('spaceId' in agent) || typeof agent.spaceId !== 'string') return false
                return allowedSpaces.has(agent.spaceId)
            }),
        }
    }
    return name === 'team_list_triggers' ? withoutTriggerUrls(result) : result
}
