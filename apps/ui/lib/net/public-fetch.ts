import { lookup } from 'node:dns/promises'
import { BlockList, isIP } from 'node:net'

const FETCH_TIMEOUT_MS = 10_000
const MAX_REDIRECTS = 3

const NON_PUBLIC = new BlockList()
for (const [network, prefix] of [
    ['0.0.0.0', 8],
    ['10.0.0.0', 8],
    ['100.64.0.0', 10],
    ['127.0.0.0', 8],
    ['169.254.0.0', 16],
    ['172.16.0.0', 12],
    ['192.168.0.0', 16],
    ['224.0.0.0', 3],
] as const)
    NON_PUBLIC.addSubnet(network, prefix, 'ipv4')
for (const [network, prefix] of [
    ['::', 127],
    ['64:ff9b::', 96],
    ['100::', 64],
    ['2001:db8::', 32],
    ['2002::', 16],
    ['fc00::', 7],
    ['fe80::', 10],
    ['ff00::', 8],
] as const)
    NON_PUBLIC.addSubnet(network, prefix, 'ipv6')

function ipv4FromMapped(address: string): string | null {
    const lower = address.toLowerCase()
    if (!lower.startsWith('::ffff:')) return null
    const tail = lower.slice(7)
    if (isIP(tail) === 4) return tail
    const parts = tail.split(':')
    if (parts.length === 2 && parts.every(part => /^[0-9a-f]{1,4}$/.test(part))) {
        const hi = parseInt(parts[0]!, 16)
        const lo = parseInt(parts[1]!, 16)
        return `${(hi >> 8) & 255}.${hi & 255}.${(lo >> 8) & 255}.${lo & 255}`
    }
    return null
}

function isPublicAddress(address: string, family: number): boolean {
    if (family === 6) {
        const mapped = ipv4FromMapped(address)
        if (mapped) return !NON_PUBLIC.check(mapped, 'ipv4')
        return !NON_PUBLIC.check(address, 'ipv6')
    }
    return !NON_PUBLIC.check(address, 'ipv4')
}

export async function resolvesToPublicAddresses(hostname: string): Promise<boolean> {
    const host = hostname.replace(/^\[|\]$/g, '')
    try {
        const addresses = isIP(host) ? [{ address: host, family: isIP(host) }] : await lookup(host, { all: true })
        return addresses.length > 0 && addresses.every(({ address, family }) => isPublicAddress(address, family))
    } catch {
        return false
    }
}

export async function assertPublicUrl(url: string): Promise<URL> {
    const parsed = new URL(url)
    if (!/^https?:$/.test(parsed.protocol) || !(await resolvesToPublicAddresses(parsed.hostname))) throw new Error(`${parsed.host || url} is not a public host`)
    return parsed
}

export async function fetchPublic(url: string, init: RequestInit = {}, { timeoutMs = FETCH_TIMEOUT_MS, maxRedirects = MAX_REDIRECTS }: { timeoutMs?: number; maxRedirects?: number } = {}): Promise<Response> {
    const method = (init.method ?? 'GET').toUpperCase()
    const followsRedirects = method === 'GET' || method === 'HEAD'
    let current = url
    for (let hop = 0; ; hop++) {
        await assertPublicUrl(current)
        const res = await fetch(current, { ...init, redirect: 'manual', signal: AbortSignal.timeout(timeoutMs) })
        const location = res.headers.get('location')
        if (!followsRedirects || res.status < 300 || res.status >= 400 || !location || hop >= maxRedirects) return res
        current = new URL(location, current).toString()
    }
}
