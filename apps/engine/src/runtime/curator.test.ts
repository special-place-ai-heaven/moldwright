import { mkdirSync, mkdtempSync, readdirSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { describe, expect, it, vi } from 'vitest'
import { z } from 'zod'
import type { LoadedAgent } from '../agents/types.js'
import type { RecalledMemory } from '../memory/store.js'
import { curationSchema, curatorPrompt, runCurator } from './curator.js'

const { generateStructuredMock, writeMemoryMock } = vi.hoisted(() => ({
    generateStructuredMock: vi.fn(),
    writeMemoryMock: vi.fn().mockResolvedValue(undefined),
}))
vi.mock('../agents/structured.js', () => ({ generateStructured: generateStructuredMock }))
vi.mock('../agents/providers.js', () => ({ modelFor: () => ({}) }))
vi.mock('../connections/cli-auth.js', () => ({ ensureCliAuth: async () => () => {} }))
vi.mock('../memory/store.js', () => ({
    recallMemory: vi.fn().mockResolvedValue([]),
    writeMemory: writeMemoryMock,
    updateMemory: vi.fn().mockResolvedValue(undefined),
    deleteMemory: vi.fn().mockResolvedValue(undefined),
}))

describe('curationSchema', () => {
    it('requires every property for strict structured output', () => {
        const schema = z.toJSONSchema(curationSchema) as { properties?: Record<string, unknown>; required?: string[] }
        expect(schema.required).toEqual(Object.keys(schema.properties ?? {}))
        expect(schema.required).toContain('obsoleteIds')
    })

    it('accepts an explicit empty obsolete id list', () => {
        expect(curationSchema.parse({ memory: null, obsoleteIds: [] })).toEqual({ memory: null, obsoleteIds: [] })
    })

    it('can only emit memory operations', () => {
        expect(Object.keys(curationSchema.shape)).toEqual(['memory', 'obsoleteIds'])
    })
})

describe('the curator never writes a skill', () => {
    it('leaves the agent skills folder untouched on disk during curation', async () => {
        const dataDir = mkdtempSync(join(tmpdir(), 'curator-skills-'))
        const prev = process.env.RERUN_DATA_DIR
        process.env.RERUN_DATA_DIR = dataDir
        try {
            const skillsDir = join(dataDir, 'agents', 'agent-1', 'skills', 'voice')
            mkdirSync(skillsDir, { recursive: true })
            writeFileSync(join(skillsDir, 'SKILL.md'), '---\nname: Voice\ndescription: Keep tone\n---\nBody\n')
            generateStructuredMock.mockResolvedValueOnce({ memory: { content: 'Ships on Fridays', updateId: null }, obsoleteIds: [] })
            const agent = {
                id: 'agent-1',
                config: { selfImprovement: { autoMemory: true }, tools: { skills: true } },
                resolved: { provider: 'openrouter', connection: {} },
            } as unknown as LoadedAgent
            await runCurator(agent, 'sess-1', 'Always format tables with pipes', 'Got it.')
            expect(readdirSync(join(dataDir, 'agents', 'agent-1', 'skills'))).toEqual(['voice'])
            expect(writeMemoryMock).toHaveBeenCalledWith(agent, 'Ships on Fridays', 'learned')
        } finally {
            if (prev === undefined) delete process.env.RERUN_DATA_DIR
            else process.env.RERUN_DATA_DIR = prev
            rmSync(dataDir, { recursive: true, force: true })
        }
    })
})

const exchange = { userText: 'Cale-toi sur ce post pour la longueur', assistantText: 'Compris.' }

describe('curatorPrompt', () => {
    it('routes how-to knowledge to a skill and forbids folding it into a memory', () => {
        const prompt = curatorPrompt({ ...exchange, existing: [], skills: [] })
        expect(prompt).toContain('Anything that says how the work is done belongs in a skill, not in memory')
        expect(prompt).toContain('never fold it into an existing memory through updateId')
        expect(prompt).toContain('Memory is the fallback for what no skill governs')
    })

    it('lists the skills that already govern the work', () => {
        const prompt = curatorPrompt({ ...exchange, existing: [], skills: [{ slug: 'write-like-clement', name: 'Write like Clement', description: 'His voice' }] })
        expect(prompt).toContain('These skills already govern how this coworker works')
        expect(prompt).toContain('- Write like Clement (slug: write-like-clement): His voice')
    })

    it('says nothing about skills when the agent has none', () => {
        const prompt = curatorPrompt({ ...exchange, existing: [], skills: [] })
        expect(prompt).not.toContain('These skills already govern')
    })

    it('still offers the existing memories for an in-place update', () => {
        const existing: RecalledMemory[] = [{ id: 'mem-1', content: 'Il poste le samedi', kind: 'learned', tags: [], createdAt: '2026-09-15T00:00:00Z', strength: 1 }]
        const prompt = curatorPrompt({ ...exchange, existing, skills: [] })
        expect(prompt).toContain('- [mem-1] (learned) Il poste le samedi')
    })
})
