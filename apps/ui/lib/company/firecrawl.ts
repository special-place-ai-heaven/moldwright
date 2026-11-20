import { normalizeDomain } from '@/lib/services/brand-icon'
import { assertPublicUrl } from '@/lib/net/public-fetch'
const FIRECRAWL_BASE_URL = process.env.RERUN_FIRECRAWL_BASE_URL ?? 'https://api.firecrawl.dev'
const SCRAPE_TIMEOUT_MS = 20_000
const MAX_MARKDOWN = 15_000

const PRIVATE_HOST = /^(localhost|127\.|10\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.|0\.|169\.254\.|100\.(6[4-9]|[7-9]\d|1[01]\d|12[0-7])\.|\[?(::1|::|::ffff:|64:ff9b:|100:|2001:db8:|2002:|f[cd][0-9a-f]{2}:|fe[89ab][0-9a-f]:|ff[0-9a-f]{2}:))/i

export function companySiteUrl(input: string): string | null {
    const domain = normalizeDomain(input)
    if (!domain.includes('.') || PRIVATE_HOST.test(domain)) return null
    if (!/^[a-z0-9.-]+\.[a-z]{2,}$/i.test(domain)) return null
    return `https://${domain}`
}

export function isPublicUrl(url: string): boolean {
    try {
        const { protocol, hostname } = new URL(url)
        return (protocol === 'https:' || protocol === 'http:') && hostname.includes('.') && !PRIVATE_HOST.test(hostname)
    } catch {
        return false
    }
}

const RATE_LIMIT_RETRY_MS = 1500

export async function scrapeCompanySite(url: string): Promise<string | null> {
    if (!process.env.FIRECRAWL_API_KEY) return null

    try {
        const body = await firecrawl<{ data?: { markdown?: string } }>('/v2/scrape', { url, formats: ['markdown'], onlyMainContent: true })
        const markdown = body.data?.markdown?.trim()
        return markdown ? markdown.slice(0, MAX_MARKDOWN) : null
    } catch {
        return null
    }
}

export async function firecrawl<T>(path: string, body: Record<string, unknown>, timeoutMs = SCRAPE_TIMEOUT_MS): Promise<T> {
    const apiKey = process.env.FIRECRAWL_API_KEY
    if (!apiKey) throw new Error('FIRECRAWL_API_KEY is not configured')

    const res = await requestFirecrawlPastRateLimit(path, body, apiKey, timeoutMs)
    if (!res.ok) throw new Error(`Firecrawl ${path} answered ${res.status}: ${(await res.text()).slice(0, 200)}`)
    return (await res.json()) as T
}

const PAGE_TIMEOUT_MS = 45_000

export type PageScrape = { status: number | null; ok: boolean; markdown: string; rawHtml: string; pageStatus: number | null }

export async function scrapePage(url: string): Promise<PageScrape | null> {
    const apiKey = process.env.FIRECRAWL_API_KEY
    if (!apiKey) return null
    try {
        await assertPublicUrl(url)
        const res = await requestFirecrawlPastRateLimit('/v2/scrape', { url, formats: ['markdown', 'rawHtml'], proxy: 'auto' }, apiKey, PAGE_TIMEOUT_MS)
        if (!res.ok) return { status: res.status, ok: false, markdown: '', rawHtml: '', pageStatus: null }

        const body = (await res.json()) as { data?: { markdown?: string; rawHtml?: string; metadata?: { statusCode?: number } } }
        const pageStatus = body.data?.metadata?.statusCode ?? null
        return { status: res.status, ok: pageStatus === null || pageStatus < 400, markdown: body.data?.markdown?.trim() ?? '', rawHtml: body.data?.rawHtml ?? '', pageStatus }
    } catch {
        return { status: null, ok: false, markdown: '', rawHtml: '', pageStatus: null }
    }
}

async function requestFirecrawlPastRateLimit(path: string, body: Record<string, unknown>, apiKey: string, timeoutMs: number): Promise<Response> {
    const res = await requestFirecrawl(path, body, apiKey, timeoutMs)
    if (res.status !== 429) return res
    await new Promise(resolve => setTimeout(resolve, RATE_LIMIT_RETRY_MS))
    return requestFirecrawl(path, body, apiKey, timeoutMs)
}

function requestFirecrawl(path: string, body: Record<string, unknown>, apiKey: string, timeoutMs: number): Promise<Response> {
    return fetch(`${FIRECRAWL_BASE_URL}${path}`, {
        method: 'POST',
        headers: { authorization: `Bearer ${apiKey}`, 'content-type': 'application/json' },
        body: JSON.stringify(body),
        signal: AbortSignal.timeout(timeoutMs),
    })
}
