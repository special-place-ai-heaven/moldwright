'use client'

import { useState } from 'react'

import type { FactoryProject as Project, FactorySnapshot } from '@rerun/contracts'

import type { FactoryProjectAnswer } from '@/app/api/_actions/factory.actions'
import { cn } from '@/lib/utils'

import { REFUSALS, activeProject, confirmText, finishingText, jobsInFlight, type ProjectsState } from './factory-project'

function stateOf(p: Project, wanted: string | null): string {
    if (p.active) return 'active'
    if (p.checking) return p.repo === wanted ? 'selected, checking' : 'checking'
    if (p.ready) return 'ready'
    return p.checkedAt ? 'not ready' : 'not checked yet'
}

export function FactoryProject({ projects, snapshot, onAdd, onSelect }: {
    projects: ProjectsState
    snapshot: FactorySnapshot | null
    onAdd: (link: string) => Promise<FactoryProjectAnswer>
    onSelect: (repo: string) => Promise<FactoryProjectAnswer>
}) {
    const [open, setOpen] = useState(false)
    const [link, setLink] = useState('')
    const [asking, setAsking] = useState<string | null>(null)
    const [busy, setBusy] = useState(false)
    const [note, setNote] = useState<string | null>(null)
    const loaded = typeof projects !== 'string' ? projects : null
    const active = activeProject(projects, snapshot)
    const owner = loaded?.owner === true
    const why = loaded ? (loaded.ownerSet ? 'Only the factory owner changes the project.' : 'No factory owner is set for this workspace.') : ''

    const run = async (call: () => Promise<FactoryProjectAnswer>, done: (repo: string) => string) => {
        setBusy(true)
        setNote(null)
        try {
            const answer = await call()
            setNote(answer.ok ? done(answer.repo) : REFUSALS[answer.reason])
            if (answer.ok) setLink('')
        } catch {
            setNote('The app did not answer. Nothing was changed.')
        } finally {
            setBusy(false)
            setAsking(null)
        }
    }
    const select = (repo: string) => run(() => onSelect(repo), r => `Checking the readiness of ${r}. It becomes the project when every line passes.`)

    return (
        <div data-project data-state={typeof projects === 'string' ? projects : loaded!.projects.length ? 'ok' : 'empty'} className="relative text-xs">
            <button type="button" data-project-toggle aria-expanded={open} onClick={() => setOpen(v => !v)}
                className="flex items-center gap-1 rounded-full border border-border/60 px-3 py-1 hover:bg-accent">
                <span className="text-muted-foreground">Project</span>
                <span data-project-active className="font-medium">{active ?? (projects === 'loading' ? 'loading' : 'none')}</span>
            </button>
            {finishingText(snapshot).map(text => <span key={text} data-project-finishing className="ml-2 text-muted-foreground">{text}</span>)}
            {open && (
                <div data-project-panel className="absolute left-0 top-full z-40 mt-3 flex w-[34rem] max-w-[90vw] flex-col gap-3 rounded-2xl border border-border/60 bg-background/95 p-3 text-left shadow-[0_8px_40px_rgba(0,0,0,0.12)] backdrop-blur-xl">
                    <div className="flex items-center justify-between">
                        <span className="font-medium">The project the factory works on</span>
                        <button type="button" data-project-close onClick={() => setOpen(false)} className="rounded px-2 py-1 text-muted-foreground hover:bg-accent">Close</button>
                    </div>
                    {projects === 'loading' && <p data-project-note>Loading the projects.</p>}
                    {projects === 'unreachable' && <p data-project-note>The list of projects cannot be read right now. The factory keeps the project it knew{active ? `: ${active}` : ''}.</p>}
                    {loaded && loaded.projects.length === 0 && <p data-project-note>No project is added yet. The factory works on its home{active ? `, ${active}` : ''}.</p>}
                    {loaded && !owner && <p data-project-readonly className="text-muted-foreground">{why}</p>}
                    {snapshot?.switch && <p data-project-switch className="text-muted-foreground">Last switch: {snapshot.switch.from} to {snapshot.switch.repo}, by {snapshot.switch.by || 'unknown'} at {snapshot.switch.at}.</p>}
                    {loaded?.previous && loaded.previous !== active && (
                        <button type="button" data-project-back disabled={!owner || busy} title={owner ? '' : why} onClick={() => select(loaded.previous!)}
                            className="self-start rounded-lg border border-border/60 px-3 py-1 enabled:hover:bg-accent disabled:opacity-50">Back to {loaded.previous}</button>
                    )}
                    {loaded?.projects.map(p => (
                        <div key={p.repo} data-project-row={p.repo} className={cn('flex flex-col gap-1 rounded-xl border p-2', p.active ? 'border-foreground/40' : 'border-border/60')}>
                            <div className="flex flex-wrap items-center gap-2">
                                <span className="font-medium">{p.repo}</span>
                                <span data-project-state className="text-muted-foreground">{stateOf(p, loaded.wanted)}</span>
                                {p.base && <span className="text-muted-foreground">base {p.base}</span>}
                                <span className="text-muted-foreground">added {p.addedAt.slice(0, 10)} by {p.addedBy}</span>
                                {!p.active && (
                                    <button type="button" data-project-select disabled={!owner || !p.ready || busy}
                                        title={!owner ? why : p.ready ? '' : 'Not ready: see the lines below.'} onClick={() => setAsking(p.repo)}
                                        className="ml-auto rounded-lg border border-border/60 px-3 py-1 enabled:hover:bg-accent disabled:opacity-50">Select</button>
                                )}
                            </div>
                            {asking === p.repo && (
                                <div data-project-confirm className="flex flex-col gap-2 rounded-lg bg-accent/50 p-2">
                                    <span>{confirmText(p.repo, active, jobsInFlight(snapshot))}</span>
                                    <div className="flex gap-2">
                                        <button type="button" data-project-yes disabled={busy} onClick={() => select(p.repo)} className="rounded-lg border border-foreground/40 px-3 py-1 hover:bg-accent">Work on {p.repo}</button>
                                        <button type="button" data-project-no onClick={() => setAsking(null)} className="rounded-lg border border-border/60 px-3 py-1 hover:bg-accent">Cancel</button>
                                    </div>
                                </div>
                            )}
                            {p.lines.map(line => (
                                <div key={line.name} data-project-line={line.ok ? 'ok' : 'failed'} className={cn('flex gap-2', line.ok ? 'text-muted-foreground' : 'text-red-600 dark:text-red-400')}>
                                    <span className="w-24 shrink-0">{line.ok ? 'ok' : 'failed'} · {line.name}</span>
                                    <span>{line.text}</span>
                                </div>
                            ))}
                        </div>
                    ))}
                    <form data-project-add className="flex gap-2" onSubmit={e => { e.preventDefault(); if (link.trim()) void run(() => onAdd(link), r => `Added ${r}. Its readiness is being checked.`) }}>
                        <input data-project-link value={link} onChange={e => setLink(e.target.value)} disabled={!owner || busy} title={owner ? '' : why}
                            placeholder="https://github.com/<owner>/<repo>" aria-label="Git link of the project to add"
                            className="min-w-0 flex-1 rounded-lg border border-border/60 bg-transparent px-3 py-1 disabled:opacity-50" />
                        <button type="submit" data-project-add-button disabled={!owner || busy || !link.trim()} title={owner ? '' : why}
                            className="rounded-lg border border-border/60 px-3 py-1 enabled:hover:bg-accent disabled:opacity-50">Add project</button>
                    </form>
                    {note && <p data-project-answer role="status">{note}</p>}
                </div>
            )}
        </div>
    )
}
