import { Agent as UndiciAgent } from 'undici'
import { refusalMessageOf, refusalResponse } from '../lib/refusal-body.js'

const CUSTOM_ENDPOINT_PATIENCE_MS = 60 * 60_000
const MAX_REFUSAL_BYTES = 64 * 1024
const MAX_REASON_CHARS = 500
const customEndpointDispatcher = new UndiciAgent({ headersTimeout: CUSTOM_ENDPOINT_PATIENCE_MS, bodyTimeout: CUSTOM_ENDPOINT_PATIENCE_MS })

async function readBoundedText(response: Response, maxBytes: number): Promise<string> {
    if (!response.body) return ''
    const reader = response.body.getReader()
    const chunks: Uint8Array[] = []
    let total = 0
    try {
        while (total < maxBytes) {
            const { done, value } = await reader.read()
            if (done || !value) break
            const take = value.byteLength <= maxBytes - total ? value : value.subarray(0, maxBytes - total)
            chunks.push(take)
            total += take.byteLength
            if (take.byteLength < value.byteLength) break
        }
    } finally {
        await reader.cancel().catch(() => {})
    }
    return Buffer.concat(chunks).toString('utf8')
}

export function customEndpointFetch(inner: typeof fetch = fetch): typeof fetch {
    return async (input, init) => {
        const response = await inner(input, { ...init, dispatcher: customEndpointDispatcher } as RequestInit)
        if (response.status !== 402) return response
        const text = await readBoundedText(response, MAX_REFUSAL_BYTES)
        const rawReason = refusalMessageOf(text) || response.statusText || 'Payment Required'
        const reason = rawReason.slice(0, MAX_REASON_CHARS)
        return refusalResponse(response, text, `Provider returned error: ${reason}`, 'custom')
    }
}
