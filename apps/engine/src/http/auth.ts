import { createHash, timingSafeEqual } from 'node:crypto'
import type { MiddlewareHandler } from 'hono'
import { env } from '../config/env.js'
import { desktopTokenMatches } from '../desktop/session.js'

const LOOPBACK_IPV4 = [127, 0, 0, 1].join('.')

function constantTimeEquals(a: string, b: string): boolean {
    const left = createHash('sha256').update(a).digest()
    const right = createHash('sha256').update(b).digest()
    return timingSafeEqual(left, right)
}

export function assertSafeBind(host: string, apiKey: string | undefined, allowUnauthenticated: boolean): void {
    if (apiKey) return
    if (allowUnauthenticated && host === LOOPBACK_IPV4) return
    if (allowUnauthenticated) {
        throw new Error(`RERUN_ALLOW_UNAUTHENTICATED=1 may only bind to ${LOOPBACK_IPV4} (got RERUN_HOST=${host})`)
    }
    throw new Error(`RERUN_API_KEY is required (or set RERUN_HOST=${LOOPBACK_IPV4} and RERUN_ALLOW_UNAUTHENTICATED=1 for local dev)`)
}

const DESKTOP_APPS_PATH = /^\/agents\/([^/]+)\/desktop\/apps$/

function isDesktopPanelRequest(method: string, path: string, token: string): boolean {
    if (method !== 'POST') return false
    const segment = DESKTOP_APPS_PATH.exec(path)?.[1]
    if (segment === undefined) return false
    let agentId: string
    try {
        agentId = decodeURIComponent(segment)
    } catch {
        return false
    }
    return desktopTokenMatches(agentId, token)
}

export const auth: MiddlewareHandler = async (c, next) => {
    const key = env().RERUN_API_KEY
    if (!key) return next()
    const header = c.req.header('authorization') ?? ''
    const token = header.startsWith('Bearer ') ? header.slice(7) : header
    if (!constantTimeEquals(token, key) && !isDesktopPanelRequest(c.req.method, c.req.path, token)) return c.json({ error: 'Unauthorized' }, 401)
    return next()
}
