import { readFileSync } from 'node:fs'
import path from 'node:path'
import { describe, expect, it } from 'vitest'
import { FACTORY_READINESS_NAMES, factoryProjectsSchema, factoryReportAnswerSchema, factorySnapshotSchema, parseProjectLink } from '@rerun/contracts'

const ROOT = path.resolve(import.meta.dirname, '../../../..')
const read = (name: string) => JSON.parse(readFileSync(path.join(ROOT, 'packages/contracts/fixtures', name), 'utf8'))
const project = () => read('factory-project.sample.json')
const whole = (extra: Record<string, unknown> = {}) => ({ ...read('factory-snapshot.sample.json'), ...project().snapshot, ...extra })
const ok = (value: unknown) => factorySnapshotSchema.safeParse(value).success
const many = <T>(one: T, n: number) => Array.from({ length: n }, () => one)

describe('the project in the factory contracts', () => {
    it('accepts a picture without any project field, as the dispatcher of before sends it', () => {
        expect(ok(read('factory-snapshot.sample.json'))).toBe(true)
    })

    it('accepts the home, what is finishing, the last switch and the readiness of the sample', () => {
        const parsed = factorySnapshotSchema.parse(whole())
        expect(parsed.home).toBe('special-place-ai-heaven/rerun')
        expect(parsed.finishing).toEqual([{ repo: 'special-place-ai-heaven/rerun', jobs: 2 }])
        expect(parsed.switch?.by).toBe('rob@example.com')
        expect(parsed.readiness?.[0].lines.map(line => line.name)).toEqual([...FACTORY_READINESS_NAMES])
    })

    it('refuses one past each limit and a name that is not owner/repo', () => {
        const s = project().snapshot
        expect(ok(whole({ finishing: many(s.finishing[0], 10) }))).toBe(true)
        expect(ok(whole({ finishing: many(s.finishing[0], 11) }))).toBe(false)
        expect(ok(whole({ readiness: many(s.readiness[0], 5) }))).toBe(true)
        expect(ok(whole({ readiness: many(s.readiness[0], 6) }))).toBe(false)
        expect(ok(whole({ readiness: [{ ...s.readiness[0], lines: many(s.readiness[0].lines[0], 12) }] }))).toBe(true)
        expect(ok(whole({ readiness: [{ ...s.readiness[0], lines: many(s.readiness[0].lines[0], 13) }] }))).toBe(false)
        expect(ok(whole({ readiness: [{ ...s.readiness[0], lines: [{ name: 'read', ok: true, text: 'x'.repeat(200) }] }] }))).toBe(true)
        expect(ok(whole({ readiness: [{ ...s.readiness[0], lines: [{ name: 'read', ok: true, text: 'x'.repeat(201) }] }] }))).toBe(false)
        expect(ok(whole({ switch: { ...s.switch, by: 'x'.repeat(100) } }))).toBe(true)
        expect(ok(whole({ switch: { ...s.switch, by: 'x'.repeat(101) } }))).toBe(false)
        for (const home of ['rerun', 'a/b/c', '../x', 'a b/c', '']) expect(ok(whole({ home }))).toBe(false)
    })

    it('refuses an unknown key inside a switch, a finishing entry, a readiness and its line', () => {
        const s = project().snapshot
        expect(ok(whole({ switch: { ...s.switch, extra: 1 } }))).toBe(false)
        expect(ok(whole({ finishing: [{ ...s.finishing[0], extra: 1 }] }))).toBe(false)
        expect(ok(whole({ readiness: [{ ...s.readiness[0], extra: 1 }] }))).toBe(false)
        expect(ok(whole({ readiness: [{ ...s.readiness[0], lines: [{ ...s.readiness[0].lines[0], extra: 1 }] }] }))).toBe(false)
    })

    it('reads the answer of factory_report: kept, the project or none, and what to check', () => {
        expect(factoryReportAnswerSchema.parse(project().answer).project?.repo).toBe('special-place-ai-heaven/testpilot')
        expect(factoryReportAnswerSchema.safeParse({ kept: false, project: null, check: [] }).success).toBe(true)
        expect(factoryReportAnswerSchema.safeParse({ kept: true }).success).toBe(false)
        expect(factoryReportAnswerSchema.safeParse({ kept: true, project: { repo: 'x', by: '' }, check: [] }).success).toBe(false)
        expect(factoryReportAnswerSchema.safeParse({ kept: true, project: null, check: many('a/b', 6) }).success).toBe(false)
        expect(factoryReportAnswerSchema.safeParse({ ...project().answer, extra: 1 }).success).toBe(false)
    })

    it('reads the list the page shows', () => {
        const list = factoryProjectsSchema.parse(project().projects)
        expect(list.projects.map(p => [p.repo, p.active, p.base])).toEqual([['special-place-ai-heaven/rerun', false, 'dev'], ['special-place-ai-heaven/testpilot', true, 'main']])
        expect(factoryProjectsSchema.safeParse({ ...project().projects, projects: many(project().projects.projects[0], 51) }).success).toBe(false)
    })

    it('turns a git link into owner/repo and refuses anything else', () => {
        const good: Array<[string, string]> = [
            ['https://github.com/special-place-ai-heaven/testpilot', 'special-place-ai-heaven/testpilot'],
            ['https://github.com/special-place-ai-heaven/testpilot.git', 'special-place-ai-heaven/testpilot'],
            ['https://github.com/special-place-ai-heaven/testpilot/', 'special-place-ai-heaven/testpilot'],
            ['  special-place-ai-heaven/terminal-commander  ', 'special-place-ai-heaven/terminal-commander'],
            ['special-place-ai-heaven/Agent_Army_Professionals.git', 'special-place-ai-heaven/Agent_Army_Professionals'],
        ]
        for (const [text, repo] of good) expect(parseProjectLink(text)).toBe(repo)
        for (const text of ['', 'testpilot', 'http://github.com/a/b', 'https://gitlab.com/a/b', 'https://github.com/a/b/tree/main', 'a/b/c', '../b', 'a/..', 'a /b', 'git@github.com:a/b.git', 'https://github.com/a/b?x=1']) {
            expect(parseProjectLink(text)).toBeNull()
        }
    })
})
