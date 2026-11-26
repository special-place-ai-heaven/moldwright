import 'server-only'

import { randomUUID } from 'node:crypto'
import {
    FACTORY_CONNECTIONS_OFF_MAX,
    FACTORY_ORDER_ISSUES_MAX,
    FACTORY_ORDER_KINDS,
    FACTORY_ORDER_TEXT_MAX,
    FACTORY_POOL_DEFAULT,
    FACTORY_QUEUE_CLEAR_MAX,
    FACTORY_QUEUE_CLEAR_WAIT_S,
    FACTORY_WIRE_ID_PATTERN,
    factoryControlStateSchema,
    factoryGhostCeiling,
    factoryProjectLimitsSchema,
    factoryStationNames,
    factoryStationSeatsSchema,
    type FactoryControlState,
    type FactoryOrderKind,
    type FactoryProjectLimits,
} from '@moldwright/contracts'
import { assertFactoryOwner, isFactoryOwner } from '@/app/api/_services/factory-projects.service'
import type { Database } from '@/app/api/database.types'
import { getFactorySnapshot } from '@/lib/factory/snapshot-store'
import { AppError } from '@/lib/i18n/action-error'
import { createServiceRoleClient } from '@/supabase/serviceRole'
import { selectMany, selectMaybeSingle } from '@/supabase/supabase-helpers'

type ControlsInsert = Database['public']['Tables']['factory_controls']['Insert']
type ControlsUpdate = Database['public']['Tables']['factory_controls']['Update']
type OrderInsert = Database['public']['Tables']['factory_work_orders']['Insert']
type OrderUpdate = Database['public']['Tables']['factory_work_orders']['Update']

const CONTROLS_COLUMNS = ['state', 'state_by', 'state_at', 'providers_off', 'providers_by', 'providers_at', 'max_ghosts', 'stations', 'throttle_by', 'throttle_at', 'project_limits', 'queue_clear', 'queue_clear_by', 'queue_clear_at'] as const
const ORDER_COLUMNS = ['id', 'repo', 'kind', 'issues', 'text', 'status', 'action', 'created_by', 'created_at', 'cancelled_by', 'cancelled_at'] as const
const ORDERS_SHOWN = 20
const STOPS: readonly FactoryControlState[] = ['DRAINING', 'STOPPED']

export type WorkOrderAction = 'retry' | 'skip'
export type FactoryWorkOrder = {
    id: string; repo: string; kind: FactoryOrderKind; issues: number[]; text: string; status: 'active' | 'cancelled'
    action: { action: WorkOrderAction; issue: number; by: string; at: string } | null
    created_at: string; cancelled_at: string | null
}
export type FactoryThrottleView = { maxGhosts: number; stations: Record<string, number> }
export type ThrottleChange = { maxGhosts: number } | { station: string; seats: number }
export type FactoryControlsView = {
    isOwner: boolean
    activeRepo: string | null
    state: FactoryControlState | null
    stateAt?: string | null
    providersOff: string[]
    throttle: FactoryThrottleView | null
    projectLimits: FactoryProjectLimits | null
    orders: FactoryWorkOrder[]
}
export type WorkOrderInput = { repo: string; kind: FactoryOrderKind; issues: number[]; text: string }

type OrderRow = { id: string; repo: string; kind: string; issues: number[]; text: string; status: string; action: unknown; created_by: string | null; created_at: string; cancelled_by: string | null; cancelled_at: string | null }

const wireTime = (at: string | number): string => new Date(at).toISOString()

function orderOf(row: OrderRow): FactoryWorkOrder {
    return {
        id: row.id, repo: row.repo, kind: row.kind as FactoryOrderKind, issues: row.issues, text: row.text,
        status: row.status === 'active' ? 'active' : 'cancelled',
        action: (row.action as FactoryWorkOrder['action']) ?? null,
        created_at: row.created_at, cancelled_at: row.cancelled_at,
    }
}

async function activeRepoOf(workspaceId: number): Promise<string | null> {
    const { data, error } = await selectMaybeSingle(createServiceRoleClient(), 'factory_projects', ['repo'] as const, { workspace_id: workspaceId, active: true })
    if (error) throw new AppError('generic')
    return data?.repo ?? null
}

async function controlsRow(workspaceId: number) {
    const { data, error } = await selectMaybeSingle(createServiceRoleClient(), 'factory_controls', CONTROLS_COLUMNS, { workspace_id: workspaceId })
    if (error) throw new AppError('generic')
    return data
}

type ControlsRow = NonNullable<Awaited<ReturnType<typeof controlsRow>>>

function throttleOf(row: ControlsRow | null): FactoryThrottleView | null {
    if (!row?.throttle_at) return null
    const stations = factoryStationSeatsSchema.safeParse(row.stations)
    return { maxGhosts: row.max_ghosts, stations: stations.success ? stations.data : {} }
}

async function ordersOf(workspaceId: number, repo?: string, limit = ORDERS_SHOWN): Promise<OrderRow[]> {
    const { data, error } = await selectMany(createServiceRoleClient(), 'factory_work_orders', ORDER_COLUMNS, repo ? { workspace_id: workspaceId, repo } : { workspace_id: workspaceId }, { column: 'created_at', ascending: false }, limit)
    if (error) throw new AppError('generic')
    return (data ?? []) as OrderRow[]
}

export async function readFactoryControls(workspaceId: number, userId: string): Promise<FactoryControlsView> {
    const [isOwner, activeRepo, row] = await Promise.all([isFactoryOwner(workspaceId, userId), activeRepoOf(workspaceId), controlsRow(workspaceId)])
    const orders = activeRepo ? await ordersOf(workspaceId, activeRepo) : []
    const state = factoryControlStateSchema.safeParse(row?.state)
    const projectLimits = factoryProjectLimitsSchema.safeParse(row?.project_limits)
    return {
        isOwner, activeRepo, state: state.success ? state.data : null, providersOff: row?.providers_off ?? [], throttle: throttleOf(row),
        stateAt: row?.state_at ?? null,
        projectLimits: projectLimits.success ? projectLimits.data : null, orders: orders.map(orderOf),
    }
}

async function cancelActiveOrders(workspaceId: number, userId: string, now: number, repo?: string): Promise<void> {
    const query = createServiceRoleClient().from('factory_work_orders')
        .update<OrderUpdate>({ status: 'cancelled', cancelled_by: userId, cancelled_at: wireTime(now) })
        .eq('workspace_id', workspaceId).eq('status', 'active')
    const { error } = await (repo ? query.eq('repo', repo) : query)
    if (error) throw new AppError('generic')
}

export async function setFactoryState(workspaceId: number, userId: string, rawState: string, now = Date.now()): Promise<void> {
    await assertFactoryOwner(workspaceId, userId)
    const state = factoryControlStateSchema.safeParse(rawState)
    if (!state.success) throw new AppError('factoryInputInvalid')
    if (STOPS.includes(state.data)) await cancelActiveOrders(workspaceId, userId, now)
    const { error } = await createServiceRoleClient().from('factory_controls')
        .upsert<ControlsInsert>({ workspace_id: workspaceId, state: state.data, state_by: userId, state_at: wireTime(now) }, { onConflict: 'workspace_id' })
    if (error) throw new AppError('generic')
}

export async function setProviderEnabled(workspaceId: number, userId: string, connectionId: string, enabled: boolean, now = Date.now()): Promise<string[]> {
    await assertFactoryOwner(workspaceId, userId)
    if (!FACTORY_WIRE_ID_PATTERN.test(connectionId)) throw new AppError('factoryInputInvalid')
    const current = (await controlsRow(workspaceId))?.providers_off ?? []
    const off = [...new Set(enabled ? current.filter(c => c !== connectionId) : [...current, connectionId])].sort()
    if (off.length > FACTORY_CONNECTIONS_OFF_MAX) throw new AppError('factoryTooManyOff', { max: FACTORY_CONNECTIONS_OFF_MAX })
    const { error } = await createServiceRoleClient().from('factory_controls')
        .upsert<ControlsInsert>({ workspace_id: workspaceId, providers_off: off, providers_by: userId, providers_at: wireTime(now) }, { onConflict: 'workspace_id' })
    if (error) throw new AppError('generic')
    return off
}

const isSeatCount = (n: number, ceiling: number): boolean => Number.isInteger(n) && n >= 0 && n <= ceiling

export async function setFactoryThrottle(workspaceId: number, userId: string, change: ThrottleChange, now = Date.now()): Promise<FactoryThrottleView> {
    await assertFactoryOwner(workspaceId, userId)
    const snapshot = getFactorySnapshot(workspaceId)?.snapshot
    const ceiling = factoryGhostCeiling(snapshot)
    const pool = 'maxGhosts' in change ? change.maxGhosts : null
    const seats = 'station' in change ? change : null
    const valid = pool !== null ? isSeatCount(pool, ceiling) : seats !== null && factoryStationNames(snapshot).includes(seats.station) && isSeatCount(seats.seats, ceiling)
    if (!valid) throw new AppError('factoryInputInvalid')
    const current = throttleOf(await controlsRow(workspaceId))
    const next: FactoryThrottleView = {
        maxGhosts: pool ?? current?.maxGhosts ?? snapshot?.throttle?.max_ghosts ?? FACTORY_POOL_DEFAULT,
        stations: seats ? { ...current?.stations, [seats.station]: seats.seats } : current?.stations ?? {},
    }
    const { error } = await createServiceRoleClient().from('factory_controls')
        .upsert<ControlsInsert>({ workspace_id: workspaceId, max_ghosts: next.maxGhosts, stations: next.stations, throttle_by: userId, throttle_at: wireTime(now) }, { onConflict: 'workspace_id' })
    if (error) throw new AppError('generic')
    return next
}

export async function setFactoryProjectLimits(workspaceId: number, userId: string, limits: unknown, now = Date.now()): Promise<FactoryProjectLimits> {
    await assertFactoryOwner(workspaceId, userId)
    const parsed = factoryProjectLimitsSchema.safeParse(limits)
    if (!parsed.success) throw new AppError('factoryInputInvalid')
    const { error } = await createServiceRoleClient().from('factory_controls')
        .upsert<ControlsInsert>({ workspace_id: workspaceId, project_limits: parsed.data, project_limits_by: userId, project_limits_at: wireTime(now) }, { onConflict: 'workspace_id' })
    if (error) throw new AppError('generic')
    return parsed.data
}

function validOrder(input: WorkOrderInput): WorkOrderInput {
    const kind = FACTORY_ORDER_KINDS.find(k => k === input?.kind)
    const issues = Array.isArray(input?.issues) ? input.issues : null
    const text = typeof input?.text === 'string' ? input.text.trim() : null
    if (!kind || !issues || text === null || typeof input.repo !== 'string') throw new AppError('factoryInputInvalid')
    if (issues.length > FACTORY_ORDER_ISSUES_MAX || new Set(issues).size !== issues.length || !issues.every(n => Number.isInteger(n) && n > 0)) throw new AppError('factoryOrderIssuesInvalid', { max: FACTORY_ORDER_ISSUES_MAX })
    if (text.length > FACTORY_ORDER_TEXT_MAX) throw new AppError('factoryOrderTextTooLong', { max: FACTORY_ORDER_TEXT_MAX })
    if ((kind === 'issue' && issues.length !== 1) || (kind === 'all_issues' && issues.length === 0)) throw new AppError('factoryOrderIssuesInvalid', { max: FACTORY_ORDER_ISSUES_MAX })
    if ((kind === 'feature' || kind === 'bug') && !text) throw new AppError('factoryOrderTextMissing')
    return { repo: input.repo, kind, issues, text }
}

async function assertActiveProject(workspaceId: number, repo: string): Promise<void> {
    if ((await activeRepoOf(workspaceId)) !== repo) throw new AppError('factoryOrderNotActiveProject', { repo })
}

export async function createWorkOrder(workspaceId: number, userId: string, input: WorkOrderInput, now = Date.now()): Promise<FactoryWorkOrder> {
    await assertFactoryOwner(workspaceId, userId)
    const order = validOrder(input)
    await assertActiveProject(workspaceId, order.repo)
    await cancelActiveOrders(workspaceId, userId, now, order.repo)
    const { data, error } = await createServiceRoleClient().from('factory_work_orders')
        .insert<OrderInsert>({ id: randomUUID(), workspace_id: workspaceId, ...order, created_by: userId, created_at: wireTime(now) })
        .select(ORDER_COLUMNS.join(','))
        .single()
    if (error?.code === '23505') throw new AppError('factoryWorkOrderActive', { repo: order.repo })
    if (error || !data) throw new AppError('generic')
    return orderOf(data as unknown as OrderRow)
}

async function activeOrder(workspaceId: number, id: string): Promise<OrderRow> {
    const { data, error } = await selectMaybeSingle(createServiceRoleClient(), 'factory_work_orders', ORDER_COLUMNS, { workspace_id: workspaceId, id: String(id), status: 'active' })
    if (error) throw new AppError('generic')
    if (!data) throw new AppError('factoryWorkOrderNotFound')
    return data as OrderRow
}

export async function cancelWorkOrder(workspaceId: number, userId: string, id: string, now = Date.now()): Promise<void> {
    await assertFactoryOwner(workspaceId, userId)
    await activeOrder(workspaceId, id)
    const { error } = await createServiceRoleClient().from('factory_work_orders')
        .update<OrderUpdate>({ status: 'cancelled', cancelled_by: userId, cancelled_at: wireTime(now) })
        .eq('workspace_id', workspaceId).eq('id', id).eq('status', 'active')
    if (error) throw new AppError('generic')
}

export async function actOnWorkOrder(workspaceId: number, userId: string, id: string, action: WorkOrderAction, issue: number, now = Date.now()): Promise<void> {
    await assertFactoryOwner(workspaceId, userId)
    if (action !== 'retry' && action !== 'skip') throw new AppError('factoryInputInvalid')
    const order = await activeOrder(workspaceId, id)
    await assertActiveProject(workspaceId, order.repo)
    const reported = getFactorySnapshot(workspaceId)?.snapshot.work_order
    if (reported?.id !== order.id || reported.halted !== issue) throw new AppError('factoryWorkOrderNotHalted', { issue: String(issue) })
    const { error } = await createServiceRoleClient().from('factory_work_orders')
        .update<OrderUpdate>({ action: { action, issue, by: userId, at: wireTime(now) } })
        .eq('workspace_id', workspaceId).eq('id', id).eq('status', 'active')
    if (error) throw new AppError('generic')
}

const validQueueIssues = (issues: unknown[]): issues is number[] =>
    issues.length > 0 && issues.length <= FACTORY_QUEUE_CLEAR_MAX && new Set(issues).size === issues.length && issues.every(n => Number.isInteger(n) && (n as number) > 0)

export async function clearFactoryQueue(workspaceId: number, userId: string, input: { repo: string; issues: number[] }, now = Date.now()): Promise<{ id: string; count: number }> {
    await assertFactoryOwner(workspaceId, userId)
    const issues = Array.isArray(input?.issues) ? input.issues : []
    if (typeof input?.repo !== 'string' || !validQueueIssues(issues)) throw new AppError('factoryInputInvalid')
    await assertActiveProject(workspaceId, input.repo)
    const row = await controlsRow(workspaceId)
    const pending = (row?.queue_clear as { id?: unknown } | null | undefined)?.id
    if (typeof pending === 'string' && row?.queue_clear_at && now - Date.parse(row.queue_clear_at) < FACTORY_QUEUE_CLEAR_WAIT_S * 1000
        && getFactorySnapshot(workspaceId)?.snapshot.queue_clear?.id !== pending) throw new AppError('factoryQueueClearBusy')
    const id = randomUUID()
    const ask = { queue_clear: { id, repo: input.repo, issues }, queue_clear_by: userId, queue_clear_at: wireTime(now) }
    const table = createServiceRoleClient().from('factory_controls')
    if (!row) {
        const { error } = await table.insert<ControlsInsert>({ workspace_id: workspaceId, ...ask })
        if (error?.code === '23505') throw new AppError('factoryQueueClearBusy')
        if (error) throw new AppError('generic')
        return { id, count: issues.length }
    }
    const update = table.update<ControlsUpdate>(ask).eq('workspace_id', workspaceId)
    const { data, error } = await (row.queue_clear_at ? update.eq('queue_clear_at', row.queue_clear_at) : update.is('queue_clear_at', null)).select('workspace_id')
    if (error) throw new AppError('generic')
    if (!data?.length) throw new AppError('factoryQueueClearBusy')
    return { id, count: issues.length }
}

function queueClearAnswer(row: ControlsRow | null | undefined): Pick<ControlsReportAnswer, 'queue_clear'> {
    const ask = row?.queue_clear as { id?: unknown; repo?: unknown; issues?: unknown } | null | undefined
    if (!row?.queue_clear_at || !ask || typeof ask.id !== 'string' || typeof ask.repo !== 'string' || !Array.isArray(ask.issues) || !validQueueIssues(ask.issues)) return {}
    return { queue_clear: { id: ask.id, repo: ask.repo, issues: ask.issues, by: row.queue_clear_by ?? '', at: wireTime(row.queue_clear_at) } }
}

export type ControlsReportAnswer = {
    control?: { state: FactoryControlState; by: string; at: string }
    providers?: { off: string[]; by: string; at: string }
    throttle?: { max_ghosts: number; stations: Record<string, number>; by: string; at: string }
    work_order?: { id: string; repo: string; kind: FactoryOrderKind; issues: number[]; text: string; by: string; at: string } | { kind: 'none'; by: string; at: string }
    work_order_action?: { action: WorkOrderAction; order_id: string; issue: number; by: string; at: string }
    queue_clear?: { id: string; repo: string; issues: number[]; by: string; at: string }
}

function orderAnswer(row: OrderRow | undefined): Pick<ControlsReportAnswer, 'work_order' | 'work_order_action'> {
    if (!row) return {}
    if (row.status !== 'active') return row.cancelled_at ? { work_order: { kind: 'none', by: row.cancelled_by ?? '', at: wireTime(row.cancelled_at) } } : {}
    const order = orderOf(row)
    return {
        work_order: { id: order.id, repo: order.repo, kind: order.kind, issues: order.issues, text: order.text, by: row.created_by ?? '', at: wireTime(row.created_at) },
        ...(order.action ? { work_order_action: { action: order.action.action, order_id: order.id, issue: order.action.issue, by: order.action.by, at: order.action.at } } : {}),
    }
}

export async function controlsReportAnswer(workspaceId: number): Promise<ControlsReportAnswer> {
    const [row, activeRepo] = await Promise.all([controlsRow(workspaceId), activeRepoOf(workspaceId)])
    const state = factoryControlStateSchema.safeParse(row?.state)
    const throttle = throttleOf(row)
    return {
        ...(state.success && row?.state_at ? { control: { state: state.data, by: row.state_by ?? '', at: wireTime(row.state_at) } } : {}),
        ...(row?.providers_at ? { providers: { off: row.providers_off, by: row.providers_by ?? '', at: wireTime(row.providers_at) } } : {}),
        ...(throttle && row?.throttle_at ? { throttle: { max_ghosts: throttle.maxGhosts, stations: throttle.stations, by: row.throttle_by ?? '', at: wireTime(row.throttle_at) } } : {}),
        ...queueClearAnswer(row),
        ...(activeRepo ? orderAnswer((await ordersOf(workspaceId, activeRepo, 1))[0]) : {}),
    }
}
