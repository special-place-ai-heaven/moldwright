import 'server-only'

import type { SupabaseClient } from '@supabase/supabase-js'

import { factoryReadinessLineSchema, parseProjectLink, type FactoryProject, type FactoryProjects, type FactoryReadinessLine, type FactorySnapshot } from '@rerun/contracts'

import type { Database, Json } from '@/app/api/database.types'

export type ProjectRow = Database['public']['Tables']['factory_projects']['Row']
export type ProjectInsert = Database['public']['Tables']['factory_projects']['Insert']
export type ProjectPatch = Database['public']['Tables']['factory_projects']['Update']

export type ProjectRows = {
    list(workspaceId: number): Promise<ProjectRow[]>
    insert(row: ProjectInsert): Promise<void>
    update(workspaceId: number, repo: string, patch: ProjectPatch): Promise<void>
    owner(workspaceId: number): Promise<string | null>
}

export const FACTORY_PROJECTS_MAX = 50
export const FACTORY_CHECK_SKEW_MS = 5_000
export const FACTORY_SEEDED_BY = 'factory'

export function projectRows(supabase: SupabaseClient<Database>): ProjectRows {
    return {
        async list(workspaceId) {
            const { data, error } = await supabase.from('factory_projects').select('*').eq('workspace_id', workspaceId).order('added_at', { ascending: true })
            if (error) throw new Error(error.message)
            return data ?? []
        },
        async insert(row) {
            const { error } = await supabase.from('factory_projects').insert(row)
            if (error) throw new Error(error.message)
        },
        async update(workspaceId, repo, patch) {
            const { error } = await supabase.from('factory_projects').update(patch).eq('workspace_id', workspaceId).eq('repo', repo)
            if (error) throw new Error(error.message)
        },
        async owner(workspaceId) {
            const { data, error } = await supabase.from('workspaces').select('factory_owner').eq('id', workspaceId).maybeSingle()
            if (error) throw new Error(error.message)
            return data?.factory_owner ?? null
        },
    }
}

export type AddResult = { ok: true; repo: string } | { ok: false; reason: 'link' | 'full' }
export type SelectResult = { ok: true; repo: string } | { ok: false; reason: 'unknown' | 'active' }

export async function addFactoryProject(rows: ProjectRows, workspaceId: number, link: string, by: string, now = new Date()): Promise<AddResult> {
    const repo = parseProjectLink(link)
    if (!repo) return { ok: false, reason: 'link' }
    const list = await rows.list(workspaceId)
    if (list.some(row => row.repo === repo)) {
        await rows.update(workspaceId, repo, { check_asked_at: now.toISOString() })
        return { ok: true, repo }
    }
    if (list.length >= FACTORY_PROJECTS_MAX) return { ok: false, reason: 'full' }
    await rows.insert({ workspace_id: workspaceId, repo, link: link.trim().slice(0, 300), added_by: by.slice(0, 100), check_asked_at: now.toISOString() })
    return { ok: true, repo }
}

export async function selectFactoryProject(rows: ProjectRows, workspaceId: number, repo: string, by: string, now = new Date()): Promise<SelectResult> {
    const list = await rows.list(workspaceId)
    const row = list.find(r => r.repo === repo)
    if (!row) return { ok: false, reason: 'unknown' }
    if (row.active) return { ok: false, reason: 'active' }
    for (const other of list) {
        if (other.wanted && other.repo !== repo) await rows.update(workspaceId, other.repo, { wanted: false })
    }
    await rows.update(workspaceId, repo, { wanted: true, check_asked_at: now.toISOString(), selected_by: by.slice(0, 100) })
    return { ok: true, repo }
}

export type ReportAnswer = { project: { repo: string; by: string } | null; check: string[] }

export async function takeFactoryReport(rows: ProjectRows, workspaceId: number, snapshot: FactorySnapshot, now = new Date()): Promise<ReportAnswer> {
    const at = now.toISOString()
    let list = await rows.list(workspaceId)
    if (snapshot.home && list.length === 0) {
        await rows.insert({ workspace_id: workspaceId, repo: snapshot.home, link: snapshot.home, added_by: FACTORY_SEEDED_BY, active: true, ready: true, selected_at: at, selected_by: FACTORY_SEEDED_BY, check_asked_at: at })
        list = await rows.list(workspaceId)
    }
    for (const result of snapshot.readiness ?? []) {
        const row = list.find(r => r.repo === result.repo)
        if (!row || (row.checked_at && Date.parse(row.checked_at) >= Date.parse(result.at))) continue
        const patch: ProjectPatch = { readiness: result.lines as Json, ready: result.passed, base_branch: result.base, checked_at: result.at }
        if (row.check_asked_at && Date.parse(result.at) >= Date.parse(row.check_asked_at) - FACTORY_CHECK_SKEW_MS) patch.check_asked_at = null
        await rows.update(workspaceId, row.repo, patch)
        Object.assign(row, patch)
    }
    const wanted = list.find(r => r.wanted)
    if (wanted && !wanted.check_asked_at) {
        if (wanted.ready) {
            const before = list.find(r => r.active && r.repo !== wanted.repo)
            if (before) {
                await rows.update(workspaceId, before.repo, { active: false, left_at: at })
                Object.assign(before, { active: false, left_at: at })
            }
            await rows.update(workspaceId, wanted.repo, { active: true, wanted: false, selected_at: at })
            Object.assign(wanted, { active: true, wanted: false, selected_at: at })
        } else {
            await rows.update(workspaceId, wanted.repo, { wanted: false })
            wanted.wanted = false
        }
    }
    const active = list.find(r => r.active)
    return {
        project: active ? { repo: active.repo, by: (active.selected_by ?? '').slice(0, 100) } : null,
        check: list.filter(r => r.check_asked_at).map(r => r.repo).slice(0, 5),
    }
}

function linesOf(value: Json): FactoryReadinessLine[] {
    const parsed = factoryReadinessLineSchema.array().max(12).safeParse(value)
    return parsed.success ? parsed.data : []
}

const iso = (value: string | null) => (value ? new Date(value).toISOString() : null)

export function toFactoryProject(row: ProjectRow): FactoryProject {
    return {
        repo: row.repo, link: row.link, base: row.base_branch, addedAt: new Date(row.added_at).toISOString(), addedBy: row.added_by,
        active: row.active, ready: row.ready, checking: Boolean(row.check_asked_at), checkedAt: iso(row.checked_at), lines: linesOf(row.readiness),
        selectedAt: iso(row.selected_at), selectedBy: row.selected_by, leftAt: iso(row.left_at),
    }
}

export async function listFactoryProjects(rows: ProjectRows, workspaceId: number): Promise<Pick<FactoryProjects, 'active' | 'wanted' | 'previous' | 'projects'>> {
    const list = await rows.list(workspaceId)
    const left = list.filter(r => !r.active && r.left_at).sort((a, b) => Date.parse(b.left_at!) - Date.parse(a.left_at!))
    return {
        active: list.find(r => r.active)?.repo ?? null,
        wanted: list.find(r => r.wanted)?.repo ?? null,
        previous: left[0]?.repo ?? null,
        projects: list.slice(0, FACTORY_PROJECTS_MAX).map(toFactoryProject),
    }
}
