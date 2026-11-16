import type { FactoryProjects, FactorySnapshot } from '@rerun/contracts'

import type { FactoryProjectRefusal } from '@/app/api/_actions/factory.actions'

export type ProjectsState = FactoryProjects | 'loading' | 'unreachable'

const ENDED = new Set(['merged', 'rejected', 'blocked', 'failed', 'returned', 'superseded', 'waiting'])

export function activeProject(projects: ProjectsState, snapshot: FactorySnapshot | null): string | null {
    if (typeof projects !== 'string' && projects.active) return projects.active
    return snapshot?.repo ?? null
}

export function jobsInFlight(snapshot: FactorySnapshot | null): number {
    return snapshot ? snapshot.jobs.filter(j => !ENDED.has(j.state)).length : 0
}

export function finishingText(snapshot: FactorySnapshot | null): string[] {
    return (snapshot?.finishing ?? []).filter(f => f.jobs > 0).map(f => `finishing ${f.jobs} ${f.jobs === 1 ? 'job' : 'jobs'} of ${f.repo}`)
}

export function snapshotFits(projects: ProjectsState, snapshot: FactorySnapshot | null): boolean {
    if (!snapshot || typeof projects === 'string') return true
    if (!projects.active) return !snapshot.home || snapshot.repo === snapshot.home
    return snapshot.repo === projects.active || snapshot.repo === projects.previous || (snapshot.finishing ?? []).some(f => f.repo === projects.active)
}

export function confirmText(repo: string, active: string | null, inFlight: number): string {
    const rest = active && inFlight > 0
        ? `The ${inFlight} ${inFlight === 1 ? 'job' : 'jobs'} in flight of ${active} finish their path (build, review, proof, merge); nothing is cancelled.`
        : 'No job is in flight; nothing is cancelled.'
    return `Work on ${repo}? Its readiness is checked again first. New jobs then come only from ${repo}. ${rest}`
}

export const REFUSALS: Record<FactoryProjectRefusal, string> = {
    owner: 'Refused: only the factory owner changes the project.',
    link: 'Not a git link. Write https://github.com/<owner>/<repo> or <owner>/<repo>.',
    full: 'Refused: 50 projects are added already.',
    unknown: 'Refused: this project is not in the list. Add it first.',
    active: 'The factory already works on this project.',
}
