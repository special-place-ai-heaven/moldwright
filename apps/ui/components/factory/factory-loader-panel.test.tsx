import { readFileSync } from 'node:fs'
import path from 'node:path'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { factorySnapshotSchema, type FactorySnapshot } from '@moldwright/contracts'
import { FactoryLoader } from './FactoryLoader'

const ROOT = path.resolve(import.meta.dirname, '../../../..')
const SAMPLE = path.join(ROOT, 'packages/contracts/fixtures/factory-snapshot.sample.json')
const sample = (): FactorySnapshot => factorySnapshotSchema.parse(JSON.parse(readFileSync(SAMPLE, 'utf8')))
const MADE = Date.parse('2026-11-14T03:24:30Z')
const html = (snapshot: FactorySnapshot | null, now = MADE + 10_000) =>
    renderToStaticMarkup(<FactoryLoader snapshot={snapshot} now={now} />)

describe('FactoryLoader', () => {
    it('shows the beat, the last beat time and that it answers', () => {
        const h = html(sample())
        expect(h).toContain('Beat 412')
        expect(h).toContain('03:24:30')
        expect(h).toContain('Answering')
    })

    it('says not answering, and when, once the picture is older than two beats', () => {
        const h = html(sample(), MADE + 5 * 60_000)
        expect(h).toContain('Not answering')
        expect(h).toContain('5 min')
    })

    it('shows the queue with what each waiting job waits on', () => {
        const h = html(sample())
        expect(h).toContain('#332')
        expect(h).toContain('waits on #331 (reviewing)')
        const fileWait = sample()
        fileWait.jobs = fileWait.jobs.map(j => (j.issue === 332 ? { ...j, reason: 'waits for #331, same file a/b.py' } : j))
        expect(html(fileWait)).toContain('waits for #331, same file a/b.py')
        expect(html(fileWait)).not.toContain('waits on #331')
        for (const state of ['merged', 'superseded'] as const) {
            const legacy = sample()
            legacy.jobs.find(j => j.issue === 331)!.state = state
            const waiting = legacy.jobs.find(j => j.issue === 332)!
            expect(waiting.waitingOn).toBeUndefined()
            expect(html(legacy)).not.toContain('waits on #331')

            waiting.dependsOn = [331, 999]
            waiting.reason = 'waits on #331, dead #999 (closed as not planned)'
            const deadWait = html(legacy)
            expect(deadWait).toContain('waits on dead #999 (closed as not planned)')
            expect(deadWait).not.toContain('waits on #331')

            waiting.dependsOn.push(334)
            waiting.reason = 'waits on #331, #334, dead #999 (closed as not planned)'
            expect(html(legacy)).toContain('waits on #334, dead #999 (closed as not planned)')

            waiting.dependsOn = [331]
            waiting.reason = 'waits for #331, same file a/b.py'
            expect(html(legacy)).toContain(waiting.reason)
            waiting.reason = 'fact recheck'
            expect(html(legacy)).toContain(waiting.reason)
        }
        const s = sample()
        s.jobs = s.jobs.filter(j => j.state !== 'waiting' && j.state !== 'queued')
        expect(html(s)).toContain('Nothing queued or waiting')
    })

    it('shows the hold with its kind and time left', () => {
        const h = html(sample())
        expect(h).toContain('sign-in renewal')
        expect(h).toContain('10:00')
        expect(html({ ...sample(), holds: [] })).toContain('No hold')
    })

    it('shows the pools and the ended counts', () => {
        const h = html(sample())
        expect(h).toContain('code')
        expect(h).toContain('2 / 6')
        expect(h).toMatch(/merged[^0-9]*1\b/)
    })

    it('has no control', () => {
        const h = html(sample())
        for (const tag of ['<button', '<a ', '<input', '<select']) expect(h).not.toContain(tag)
    })

    it('renders the sample-loop line when there is no picture', () => {
        const h = html(null)
        expect(h).toContain('No picture from the Loader yet. The floor is playing its sample loop.')
        expect(h).not.toContain('Beat')
    })
})
