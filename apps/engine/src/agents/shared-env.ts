import { existsSync, readdirSync, readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { mcpDir, sharedEnvPath } from '../config/paths.js'
import { parseEnvFile, writeEnvFile } from '../lib/env-file.js'
import type { LoadedAgent } from './types.js'

const SECRET_NAME = /(TOKEN|KEY|SECRET|PASSWORD|AUTH|COOKIE|DSN|DATABASE_URL)/i
const SECRET_MIN_LENGTH = 8

export function readSharedEnvSync(): Record<string, string> {
    return existsSync(sharedEnvPath()) ? parseEnvFile(readFileSync(sharedEnvPath(), 'utf8')) : {}
}

export async function writeSharedEnv(env: Record<string, string>): Promise<void> {
    await writeEnvFile(sharedEnvPath(), env)
}

export function secretValuesOf(env: Record<string, string>): string[] {
    return Object.entries(env)
        .filter(([name, value]) => SECRET_NAME.test(name) && value.length >= SECRET_MIN_LENGTH)
        .map(([, value]) => value)
}

function mcpStoredSecrets(agentId: string): string[] {
    const dir = mcpDir(agentId)
    if (!existsSync(dir)) return []
    const values: string[] = []
    try {
        for (const name of readdirSync(dir)) {
            if (!name.endsWith('.json') || name.endsWith('.pending.json')) continue
            try {
                const parsed = JSON.parse(readFileSync(resolve(dir, name), 'utf8')) as { accessToken?: unknown; refreshToken?: unknown; clientSecret?: unknown }
                for (const v of [parsed.accessToken, parsed.refreshToken, parsed.clientSecret]) {
                    if (typeof v === 'string' && v.length >= SECRET_MIN_LENGTH) values.push(v)
                }
            } catch {
                continue
            }
        }
    } catch {
        return []
    }
    return values
}

export function agentSecretValues(agent: Pick<LoadedAgent, 'id' | 'env'> & { resolved?: { connection?: { env?: Record<string, string> } | null } }): string[] {
    const all = [
        ...Object.values(agent.env),
        ...Object.values(agent.resolved?.connection?.env ?? {}),
        ...secretValuesOf(readSharedEnvSync()),
        ...mcpStoredSecrets(agent.id),
    ].filter(value => value.length >= SECRET_MIN_LENGTH)
    return [...new Set(all)]
}
