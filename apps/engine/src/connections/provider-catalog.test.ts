import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { connectionConfigSchema, type Provider } from '@moldwright/contracts'
import { providerDiscoveredModels, refreshProviderCatalog, refreshStaleProviderCatalogs, resetProviderCatalogForTests } from './provider-catalog.js'
import { toSummary } from './loader.js'
import { servesModel } from './resolve.js'
import { allowedModel } from './plan.js'
import { runContextWindow } from '../runtime/compaction/compact.js'

const fixture = (name: string): string => readFileSync(resolve(import.meta.dirname, '__fixtures__/provider-models', `${name}.json`), 'utf8')

type Seen = { url: string; headers: Record<string, string> }
const seen: Seen[] = []
let answer: (url: URL) => Response

function connection(provider: Provider, env: Record<string, string>, extra: Record<string, unknown> = {}) {
    return { id: `cnx-${provider}`, config: connectionConfigSchema.parse({ name: provider, provider, createdAt: '2026-11-20T00:00:00.000Z', ...extra }), env }
}

const ok = (body: string) => new Response(body, { status: 200, headers: { 'Content-Type': 'application/json' } })

beforeEach(() => {
    resetProviderCatalogForTests()
    seen.length = 0
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
        const url = new URL(String(input))
        seen.push({ url: url.toString(), headers: Object.fromEntries(new Headers(init?.headers).entries()) })
        return answer(url)
    })
})

afterEach(() => {
    vi.restoreAllMocks()
})

describe('the live model list of a key connection', () => {
    it('reads OpenRouter from the connection base URL and lists it in the summary', async () => {
        answer = () => ok(fixture('openrouter'))
        const cnx = connection('openrouter', { OPENROUTER_API_KEY: 'sk-or-secret' }, { baseUrl: 'https://router.example/api/v1/' })
        expect(toSummary(cnx).discoveredModels).toBeNull()

        await refreshProviderCatalog(cnx)

        expect(seen[0].url).toBe('https://router.example/api/v1/models')
        expect(seen[0].headers.authorization).toBe('Bearer sk-or-secret')
        const listed = toSummary(cnx).discoveredModels
        expect(listed?.map(model => model.id)).toEqual(['google/gemini-4-carbon', 'anthropic/claude-opus-5.5', 'openrouter/auto'])
        expect(listed?.[0]).toMatchObject({ label: 'Google: Gemini 4 Carbon', contextWindow: 2_000_000, price: { input: 2.5, output: 15 } })
        expect(JSON.stringify(toSummary(cnx))).not.toContain('sk-or-secret')
    })

    it('reads OpenAI with the key', async () => {
        answer = () => ok(fixture('openai'))
        const cnx = connection('openai', { OPENAI_API_KEY: 'sk-openai' })
        await refreshProviderCatalog(cnx)
        expect(seen[0].url).toBe('https://api.openai.com/v1/models')
        expect(seen[0].headers.authorization).toBe('Bearer sk-openai')
        expect(providerDiscoveredModels(cnx.id)?.map(model => model.id)).toEqual(['gpt-6-sol', 'gpt-7-preview'])
    })

    it('reads every Google page with the key in a header, never in the address', async () => {
        answer = url => ok(fixture(url.searchParams.get('pageToken') === 'page-2' ? 'google-page2' : 'google-page1'))
        const cnx = connection('google', { GOOGLE_GENERATIVE_AI_API_KEY: 'AIza-secret' })
        await refreshProviderCatalog(cnx)
        expect(seen).toHaveLength(2)
        expect(seen.every(call => call.headers['x-goog-api-key'] === 'AIza-secret' && !call.url.includes('AIza-secret'))).toBe(true)
        expect(seen[1].url).toContain('pageToken=page-2')
        expect(providerDiscoveredModels(cnx.id)?.map(model => model.id)).toEqual(['gemini-4-argon', 'gemini-4-carbon'])
        expect(runContextWindow('gemini-4-carbon', 'google', cnx)).toBe(2_097_152)
    })

    it('reads every Anthropic page with its version header', async () => {
        answer = url => ok(fixture(url.searchParams.get('after_id') ? 'anthropic-page2' : 'anthropic-page1'))
        const cnx = connection('anthropic', { ANTHROPIC_API_KEY: 'sk-ant-api' })
        await refreshProviderCatalog(cnx)
        expect(seen[0].headers['x-api-key']).toBe('sk-ant-api')
        expect(seen[0].headers['anthropic-version']).toBe('2023-06-01')
        expect(seen[1].url).toContain('after_id=claude-sonnet-5-5')
        expect(providerDiscoveredModels(cnx.id)?.map(model => model.id)).toEqual(['claude-opus-6', 'claude-sonnet-5-5', 'claude-haiku-5-5'])
        expect(runContextWindow('claude-opus-6', 'anthropic', cnx)).toBe(1_000_000)
    })

    it('keeps the last good list when a later read fails, and leaves the fallback when none succeeded', async () => {
        const cnx = connection('openai', { OPENAI_API_KEY: 'sk-openai' })
        answer = () => new Response('{}', { status: 500 })
        await refreshProviderCatalog(cnx)
        expect(toSummary(cnx).discoveredModels).toBeNull()

        answer = () => ok(fixture('openai'))
        await refreshProviderCatalog(cnx)
        answer = () => {
            throw new TypeError('fetch failed')
        }
        await refreshProviderCatalog(cnx)
        expect(toSummary(cnx).discoveredModels).toHaveLength(2)

        answer = () => ok('{"data":[]}')
        await refreshProviderCatalog(cnx)
        expect(toSummary(cnx).discoveredModels).toHaveLength(2)
    })

    it('refuses an answer larger than the size cap', async () => {
        answer = () => ok(JSON.stringify({ data: [{ id: 'x'.repeat(9 * 1024 * 1024) }] }))
        const cnx = connection('openai', { OPENAI_API_KEY: 'sk-openai' })
        await refreshProviderCatalog(cnx)
        expect(providerDiscoveredModels(cnx.id)).toBeNull()
    })

    it('does not read without a key and leaves other providers alone', async () => {
        answer = () => ok(fixture('openai'))
        await refreshProviderCatalog(connection('openai', {}))
        await refreshProviderCatalog(connection('claude', { CLAUDE_CODE_OAUTH_TOKEN: 't' }))
        expect(seen).toHaveLength(0)
    })

    it('rereads only once the last attempt is stale', async () => {
        answer = () => ok(fixture('openai'))
        const cnx = connection('openai', { OPENAI_API_KEY: 'sk-openai' })
        await refreshProviderCatalog(cnx)
        refreshStaleProviderCatalogs([cnx])
        expect(seen).toHaveLength(1)
    })
})

describe('a model only the live OpenRouter list has', () => {
    it('can be turned on and is then served as is', async () => {
        answer = () => ok(fixture('openrouter'))
        const cnx = connection('openrouter', { OPENROUTER_API_KEY: 'sk-or' }, { models: ['anthropic/claude-sonnet-5.5'] })
        await refreshProviderCatalog(cnx)
        expect(servesModel(cnx, 'google/gemini-4-carbon')).toBe(false)

        const enabled = { ...cnx, config: connectionConfigSchema.parse({ ...cnx.config, models: [...cnx.config.models, 'google/gemini-4-carbon'] }) }
        expect(servesModel(enabled, 'google/gemini-4-carbon')).toBe(true)
        expect(allowedModel('openrouter', 'google/gemini-4-carbon')).toBe('google/gemini-4-carbon')
        expect(runContextWindow('google/gemini-4-carbon', 'openrouter', enabled)).toBe(2_000_000)
    })
})
