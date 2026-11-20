import { CONNECTION_TOKEN_KEY, type DiscoveredModel, type Provider } from '@moldwright/contracts'
import { logger } from '../lib/logger.js'
import { trimBaseUrl } from './custom-catalog.js'
import { anthropicNextPage, googleNextPage, parseAnthropicModels, parseGoogleModels, parseOpenaiModels, parseOpenrouterModels } from './provider-model-lists.js'
import type { LoadedConnection } from './types.js'

const FETCH_TIMEOUT_MS = 10_000
const STALE_AFTER_MS = 30 * 60_000
const MAX_BODY_BYTES = 8 * 1024 * 1024
const MAX_PAGES = 20
const OPENROUTER_DEFAULT_BASE_URL = 'https://openrouter.ai/api/v1'
const OPENAI_MODELS_URL = 'https://api.openai.com/v1/models'
const GOOGLE_MODELS_URL = 'https://generativelanguage.googleapis.com/v1beta/models'
const ANTHROPIC_MODELS_URL = 'https://api.anthropic.com/v1/models'
const ANTHROPIC_VERSION = '2023-06-01'

type Page = { url: string; headers: Record<string, string> }
type Lister = {
    first: (connection: LoadedConnection, key: string) => Page
    next: (body: unknown, page: Page) => Page | null
    parse: (body: unknown) => DiscoveredModel[]
}

const single = (): null => null

function withParam(page: Page, name: string, value: string | null): Page | null {
    if (!value) return null
    const url = new URL(page.url)
    url.searchParams.set(name, value)
    return { ...page, url: url.toString() }
}

const LISTERS: Partial<Record<Provider, Lister>> = {
    openrouter: {
        first: (connection, key) => ({ url: `${trimBaseUrl(connection.config.baseUrl || OPENROUTER_DEFAULT_BASE_URL)}/models`, headers: { Authorization: `Bearer ${key}` } }),
        next: single,
        parse: parseOpenrouterModels,
    },
    openai: {
        first: (_connection, key) => ({ url: OPENAI_MODELS_URL, headers: { Authorization: `Bearer ${key}` } }),
        next: single,
        parse: parseOpenaiModels,
    },
    google: {
        first: (_connection, key) => ({ url: `${GOOGLE_MODELS_URL}?pageSize=1000`, headers: { 'x-goog-api-key': key } }),
        next: (body, page) => withParam(page, 'pageToken', googleNextPage(body)),
        parse: parseGoogleModels,
    },
    anthropic: {
        first: (_connection, key) => ({ url: `${ANTHROPIC_MODELS_URL}?limit=1000`, headers: { 'x-api-key': key, 'anthropic-version': ANTHROPIC_VERSION } }),
        next: (body, page) => withParam(page, 'after_id', anthropicNextPage(body)),
        parse: parseAnthropicModels,
    },
}

type Reading = { models: DiscoveredModel[]; at: number }
const readings = new Map<string, Reading>()
const attemptedAt = new Map<string, number>()
const inFlight = new Map<string, Promise<void>>()

function keyOf(connection: LoadedConnection): string | undefined {
    const { env, config } = connection
    const key = env[CONNECTION_TOKEN_KEY[config.provider]] || (config.provider === 'google' ? env.GOOGLE_API_KEY : undefined)
    return key || undefined
}

async function readCapped(response: Response): Promise<unknown> {
    if (Number(response.headers.get('content-length')) > MAX_BODY_BYTES) throw new Error('model list too large')
    const reader = response.body?.getReader()
    if (!reader) return null
    const chunks: Uint8Array[] = []
    let size = 0
    for (let chunk = await reader.read(); !chunk.done; chunk = await reader.read()) {
        size += chunk.value.byteLength
        if (size > MAX_BODY_BYTES) {
            await reader.cancel()
            throw new Error('model list too large')
        }
        chunks.push(chunk.value)
    }
    return JSON.parse(Buffer.concat(chunks).toString('utf8'))
}

async function readPage(page: Page): Promise<unknown> {
    const response = await fetch(page.url, { headers: page.headers, redirect: 'error', signal: AbortSignal.timeout(FETCH_TIMEOUT_MS) })
    if (!response.ok) {
        await response.body?.cancel()
        throw new Error(`model list answered ${response.status}`)
    }
    return readCapped(response)
}

async function listModels(lister: Lister, connection: LoadedConnection, key: string): Promise<DiscoveredModel[]> {
    const models: DiscoveredModel[] = []
    let page: Page | null = lister.first(connection, key)
    for (let read = 0; page && read < MAX_PAGES; read++) {
        const body = await readPage(page)
        models.push(...lister.parse(body).filter(model => !models.some(seen => seen.id === model.id)))
        page = lister.next(body, page)
    }
    return models
}

export function listsProviderModels(provider: Provider): boolean {
    return provider in LISTERS
}

export function refreshProviderCatalog(connection: LoadedConnection): Promise<void> {
    const running = inFlight.get(connection.id)
    if (running) return running
    const lister = LISTERS[connection.config.provider]
    const key = keyOf(connection)
    if (!lister || !key) return Promise.resolve()
    attemptedAt.set(connection.id, Date.now())
    const stale = { connection: connection.id, provider: connection.config.provider, stale: readings.has(connection.id) }
    const attempt = listModels(lister, connection, key)
        .then(models => {
            if (models.length) readings.set(connection.id, { models, at: Date.now() })
            else logger.warn(stale, 'provider model list was empty, keeping the previous list')
        })
        .catch(err => logger.warn({ ...stale, err: err instanceof Error ? err.message : String(err) }, 'provider model list failed, keeping the previous list'))
        .finally(() => inFlight.delete(connection.id))
    inFlight.set(connection.id, attempt)
    return attempt
}

export function refreshStaleProviderCatalogs(connections: LoadedConnection[]): void {
    for (const connection of connections) {
        if (!listsProviderModels(connection.config.provider)) continue
        if (Date.now() - (attemptedAt.get(connection.id) ?? 0) < STALE_AFTER_MS) continue
        void refreshProviderCatalog(connection)
    }
}

export function providerDiscoveredModels(connectionId: string): DiscoveredModel[] | null {
    return readings.get(connectionId)?.models ?? null
}

export function providerContextWindow(connection: LoadedConnection | null | undefined, model: string): number | undefined {
    return (connection && readings.get(connection.id)?.models.find(entry => entry.id === model)?.contextWindow) || undefined
}

export function forgetProviderCatalog(connectionId: string): void {
    readings.delete(connectionId)
    attemptedAt.delete(connectionId)
}

export function resetProviderCatalogForTests(): void {
    readings.clear()
    attemptedAt.clear()
    inFlight.clear()
}
