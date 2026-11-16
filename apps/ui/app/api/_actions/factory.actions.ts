'use server'

import type { FactoryProjects, FactorySnapshot } from '@rerun/contracts'

import { requireWorkspaceContext, requireWorkspaceId } from '@/app/api/_auth/ownership'
import { addFactoryProject, listFactoryProjects, projectRows, selectFactoryProject } from '@/lib/factory/projects'
import { getFactorySnapshot } from '@/lib/factory/snapshot-store'

export type FactoryProjectRefusal = 'owner' | 'link' | 'full' | 'unknown' | 'active'
export type FactoryProjectAnswer = { ok: true; repo: string } | { ok: false; reason: FactoryProjectRefusal }

export async function readFactorySnapshotAction(): Promise<{ snapshot: FactorySnapshot; receivedAt: number; ageMs: number } | null> {
    const workspaceId = await requireWorkspaceId()
    const held = getFactorySnapshot(workspaceId)
    if (!held) return null
    return { snapshot: held.snapshot, receivedAt: held.receivedAt, ageMs: Date.now() - held.receivedAt }
}

export async function readFactoryProjectsAction(): Promise<FactoryProjects> {
    const ctx = await requireWorkspaceContext()
    const rows = projectRows(ctx.supabase)
    const owner = await rows.owner(ctx.workspace.id)
    return { owner: owner !== null && owner === ctx.userId, ownerSet: owner !== null, ...(await listFactoryProjects(rows, ctx.workspace.id)) }
}

async function asOwner(run: (rows: ReturnType<typeof projectRows>, workspaceId: number, by: string) => Promise<FactoryProjectAnswer>): Promise<FactoryProjectAnswer> {
    const ctx = await requireWorkspaceContext()
    const rows = projectRows(ctx.supabase)
    const owner = await rows.owner(ctx.workspace.id)
    if (owner === null || owner !== ctx.userId) return { ok: false, reason: 'owner' }
    return run(rows, ctx.workspace.id, ctx.userEmail ?? ctx.userId)
}

export async function addFactoryProjectAction(link: string): Promise<FactoryProjectAnswer> {
    return asOwner((rows, workspaceId, by) => addFactoryProject(rows, workspaceId, String(link ?? ''), by))
}

export async function selectFactoryProjectAction(repo: string): Promise<FactoryProjectAnswer> {
    return asOwner((rows, workspaceId, by) => selectFactoryProject(rows, workspaceId, String(repo ?? ''), by))
}
