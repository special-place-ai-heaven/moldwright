import { z } from 'zod'

const isoTime = z.string().max(40).datetime({ offset: true })
const count = z.number().int().min(0)

export const FACTORY_REPO_PATTERN = /^[A-Za-z0-9][A-Za-z0-9_.-]{0,99}\/[A-Za-z0-9_.-]{1,100}$/
export const FACTORY_READINESS_NAMES = ['owner', 'read', 'push', 'pull requests', 'base', 'labels', 'checks', 'proof', 'issues'] as const

export const factoryRepoSchema = z.string().max(201).regex(FACTORY_REPO_PATTERN)

export function parseProjectLink(text: string): string | null {
    const trimmed = text.trim()
    const linked = /^https:\/\/github\.com\/([^/\s]+)\/([^/\s]+?)(?:\.git)?\/?$/.exec(trimmed)
    const repo = linked ? `${linked[1]}/${linked[2]}` : trimmed.replace(/\.git$/, '')
    return FACTORY_REPO_PATTERN.test(repo) && !repo.split('/').some(part => part === '.' || part === '..') ? repo : null
}

export const factoryReadinessLineSchema = z.object({
    name: z.string().min(1).max(40),
    ok: z.boolean(),
    text: z.string().max(200),
}).strict()

export const factoryReadinessSchema = z.object({
    repo: factoryRepoSchema,
    at: isoTime,
    passed: z.boolean(),
    base: z.string().max(200).nullable(),
    redgreen: z.boolean(),
    lines: z.array(factoryReadinessLineSchema).max(12),
}).strict()

export const factorySwitchSchema = z.object({
    repo: factoryRepoSchema,
    from: factoryRepoSchema,
    by: z.string().max(100),
    at: isoTime,
}).strict()

export const factoryFinishingSchema = z.object({ repo: factoryRepoSchema, jobs: count }).strict()

export const factoryReportAnswerSchema = z.object({
    kept: z.boolean(),
    project: z.object({ repo: factoryRepoSchema, by: z.string().max(100) }).strict().nullable(),
    check: z.array(factoryRepoSchema).max(5),
}).strict()

export const factoryProjectSchema = z.object({
    repo: factoryRepoSchema,
    link: z.string().max(300),
    base: z.string().max(200).nullable(),
    addedAt: isoTime,
    addedBy: z.string().max(100),
    active: z.boolean(),
    ready: z.boolean(),
    checking: z.boolean(),
    checkedAt: isoTime.nullable(),
    lines: z.array(factoryReadinessLineSchema).max(12),
    selectedAt: isoTime.nullable(),
    selectedBy: z.string().max(100).nullable(),
    leftAt: isoTime.nullable(),
}).strict()

export const factoryProjectsSchema = z.object({
    owner: z.boolean(),
    ownerSet: z.boolean(),
    active: factoryRepoSchema.nullable(),
    wanted: factoryRepoSchema.nullable(),
    previous: factoryRepoSchema.nullable(),
    projects: z.array(factoryProjectSchema).max(50),
}).strict()

export type FactoryReadinessLine = z.infer<typeof factoryReadinessLineSchema>
export type FactoryReadiness = z.infer<typeof factoryReadinessSchema>
export type FactorySwitch = z.infer<typeof factorySwitchSchema>
export type FactoryFinishing = z.infer<typeof factoryFinishingSchema>
export type FactoryReportAnswer = z.infer<typeof factoryReportAnswerSchema>
export type FactoryProject = z.infer<typeof factoryProjectSchema>
export type FactoryProjects = z.infer<typeof factoryProjectsSchema>
