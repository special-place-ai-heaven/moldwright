import type { FactoryJobState, FactorySnapshot, FactoryWorkerType } from '@moldwright/contracts'

export const BEAT_MS = 30_000

export const isAnswering = (madeAt: string, now: number) => now - Date.parse(madeAt) <= 2 * BEAT_MS

export type LoaderView = {
    alive: { beat: number; lastBeatAt: string; ageMs: number; answering: boolean }
    waiting: { issue: number; title: string; waitsOn: { issue: number; state: FactoryJobState | null }[]; reason: string | null }[]
    queued: { position: number; issue: number; title: string }[]
    holds: { kind: string; leftMs: number }[]
    pools: { type: FactoryWorkerType; allowed: number; out: number; coworkers: { name: string; runs: number; out: number }[] }[]
    ended: FactorySnapshot['endedToday']
    endedTotal: number
}

export function loaderView(snapshot: FactorySnapshot, now: number): LoaderView {
    const ageMs = now - Date.parse(snapshot.madeAt)
    const stateOf = new Map(snapshot.jobs.map(j => [j.issue, j.state]))
    const isUnmet = (issue: number) => stateOf.get(issue) !== 'merged' && stateOf.get(issue) !== 'superseded'
    const prefix = 'waits on '
    return {
        alive: { beat: snapshot.beat, lastBeatAt: snapshot.madeAt, ageMs, answering: isAnswering(snapshot.madeAt, now) },
        waiting: snapshot.jobs
            .filter(j => j.state === 'waiting')
            .map(j => {
                const deps = j.waitingOn ?? j.dependsOn.filter(isUnmet)
                let reason: string | null = j.reason
                if (j.waitingOn === undefined && reason?.startsWith(prefix)) {
                    const parts = reason.slice(prefix.length).split(', ').filter(part => {
                        const issue = part.match(/#(\d+)/)
                        return issue === null || isUnmet(Number(issue[1]))
                    })
                    reason = parts.length ? prefix + parts.join(', ') : null
                }
                return {
                    issue: j.issue,
                    title: j.title,
                    waitsOn: deps.map(d => ({ issue: d, state: stateOf.get(d) ?? null })),
                    reason,
                }
            }),
        queued: snapshot.jobs
            .filter(j => j.state === 'queued')
            .map((j, i) => ({ position: i + 1, issue: j.issue, title: j.title })),
        holds: snapshot.holds
            .map(h => ({ kind: h.kind, leftMs: Date.parse(h.until) - now }))
            .filter(h => h.leftMs > 0)
            .sort((a, b) => b.leftMs - a.leftMs),
        pools: snapshot.pools.map(p => ({
            type: p.type,
            allowed: p.coworkers.reduce((n, c) => n + c.runs, 0),
            out: p.coworkers.reduce((n, c) => n + c.out, 0),
            coworkers: p.coworkers.map(c => ({ name: c.name, runs: c.runs, out: c.out })),
        })),
        ended: snapshot.endedToday,
        endedTotal: Object.values(snapshot.endedToday).reduce((n, v) => n + v, 0),
    }
}
