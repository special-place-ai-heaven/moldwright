'use client'

import { MessageCircle } from 'lucide-react'
import { useTheme } from 'next-themes'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

import { readFactorySnapshotAction } from '@/app/api/_actions/factory.actions'
import { AgentPanel } from '@/components/agent/AgentPanel'
import { ControlCenter } from '@/components/control-center/ControlCenter'
import { FactoryLoader } from '@/components/factory/FactoryLoader'
import { FactoryTopBar } from '@/components/factory/FactoryTopBar'
import { FactoryWorld } from '@/components/factory/FactoryWorld'
import { type Bucket } from '@/components/factory/factory-bucket'
import { LOADER_TILE } from '@/components/factory/factory-state'
import { sceneFromSnapshot } from '@/components/factory/from-snapshot'
import { useFactoryControls } from '@/components/factory/use-factory-controls'
import { WorkspaceSwitcher } from '@/components/layout/WorkspaceSwitcher'
import { BAR_TIERS } from '@/components/factory/factory-bar-tiers'
import { Button } from '@/components/ui/button'
import { TooltipLabeled } from '@/components/ui/tooltip'
import { FACTORY_OVERLAY_BELOW, SIDE_PANEL_GAP, loadSidePanelWidth } from '@/lib/side-panel-width'
import { cn } from '@/lib/utils'
import { useBoardStore } from '@/stores/board.store'
import { useSession } from '@/supabase/session/SessionProvider'

const POLL_MS = 30_000
const LOADER_PANEL_PX = 380

type Answer = Awaited<ReturnType<typeof readFactorySnapshotAction>>

export function FactoryPage() {
    const session = useSession()
    return <WorkspaceFactoryPage key={session.workspace?.id ?? 'sample'} session={session} />
}

function WorkspaceFactoryPage({ session }: { session: ReturnType<typeof useSession> }) {
    const { resolvedTheme } = useTheme()
    const [answer, setAnswer] = useState<Answer>(null)

    useEffect(() => {
        let alive = true
        const read = () => {
            readFactorySnapshotAction()
                .then(next => { if (alive && next) setAnswer(next) })
                .catch(() => {})
        }
        read()
        const id = setInterval(read, POLL_MS)
        return () => {
            alive = false
            clearInterval(id)
        }
    }, [])

    const snapshot = answer?.snapshot
    const scene = useCallback((_: number, now: number) => sceneFromSnapshot(snapshot!, now), [snapshot])
    const { workspace, user, loading } = session

    const [selected, setSelected] = useState<number | null>(null)
    const [bucket, setBucket] = useState<Bucket | null>(null)
    const [loaderOpen, setLoaderOpen] = useState(false)

    const hydrated = useBoardStore(s => s.hydrated)
    const hydrate = useBoardStore(s => s.hydrate)
    const agents = useBoardStore(s => s.agents)
    const selectedAgentId = useBoardStore(s => s.selectedAgentId)
    const [viewport, setViewport] = useState(() => (typeof window === 'undefined' ? 0 : window.innerWidth))
    useEffect(() => {
        const onResize = () => setViewport(window.innerWidth)
        window.addEventListener('resize', onResize)
        return () => window.removeEventListener('resize', onResize)
    }, [])
    const hydratedWorkspaceId = useRef<number | null>(null)
    useEffect(() => {
        if (hydrated || !workspace) return
        if (hydratedWorkspaceId.current === workspace.id) return
        hydratedWorkspaceId.current = workspace.id
        hydrate(workspace.id)
    }, [hydrated, workspace, hydrate])

    const onSelect = useCallback((issue: number) => setSelected(issue), [])
    const onOpenBucket = useCallback((b: Bucket) => { setSelected(null); setBucket(b) }, [])
    useEffect(() => {
        const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') { setSelected(null); setBucket(null) } }
        window.addEventListener('keydown', onKey)
        return () => window.removeEventListener('keydown', onKey)
    }, [])

    const controls = useFactoryControls(`${snapshot?.repo}|${snapshot?.control?.at}`)
    const coworkers = useMemo(() => snapshot?.pools.flatMap(p => p.coworkers) ?? [], [snapshot])
    const names = useMemo(() => Object.fromEntries(coworkers.flatMap(c => (c.id ? [[c.id, c.name]] : []))), [coworkers])
    const openCoworker = useCallback((id: string) => {
        setLoaderOpen(false)
        useBoardStore.getState().focusAgentOnBoard(id, 'logs')
    }, [])
    const openByName = useCallback((name: string) => {
        if (name === LOADER_TILE) {
            useBoardStore.getState().selectAgent(null)
            setLoaderOpen(true)
            return
        }
        const id = coworkers.find(c => c.name === name)?.id
        if (id) openCoworker(id)
    }, [coworkers, openCoworker])

    const boss = agents.find(a => [a.handle, a.name].some(n => n?.toLowerCase() === 'boss'))
    const rightInset = viewport < FACTORY_OVERLAY_BELOW ? 0 : loaderOpen ? LOADER_PANEL_PX : selectedAgentId ? loadSidePanelWidth(viewport, true) + SIDE_PANEL_GAP : 0

    return (
        <div data-factory className="relative h-full overflow-hidden">
            <FactoryWorld
                {...(snapshot ? { scene, selectedIssue: selected, onSelectJob: onSelect, onOpenBucket, onOpenCoworker: openByName } : {})}
                {...(workspace ? { workspace: String(workspace.id) } : {})}
                cameraScope={workspace && user ? `factory:${workspace.id}:${user.id}` : loading ? null : 'factory:sample'}
                snapshot={snapshot ?? null}
                rightInset={rightInset}
                theme={resolvedTheme === 'light' ? 'light' : 'dark'}
                topBar={
                    <FactoryTopBar snapshot={snapshot ?? null} controls={controls} selected={selected} onSelect={setSelected} names={names} onOpenCoworker={openCoworker} bucket={bucket} onBucket={setBucket}
                        rightInset={rightInset}
                        context={<WorkspaceSwitcher inline pillClassName={BAR_TIERS.t3.workspaceIcon} />}
                        action={
                            <TooltipLabeled label={boss ? 'Open the chat with Boss' : 'No coworker named boss in this workspace'}>
                                <Button type="button" variant="secondary" size="sm" aria-disabled={!boss} aria-label="Talk to Boss" className={cn('aria-disabled:cursor-not-allowed aria-disabled:opacity-50', BAR_TIERS.t1.square)}
                                    onClick={() => { if (!boss) return; setLoaderOpen(false); useBoardStore.getState().focusAgentOnBoard(boss.id, 'chat') }}>
                                    <MessageCircle aria-hidden className={cn('hidden', BAR_TIERS.t1.show)} />
                                    <span className={BAR_TIERS.t1.hide}>Talk to Boss</span>
                                </Button>
                            </TooltipLabeled>
                        }
                    />
                }
            />
            {loaderOpen && (
                <aside data-loader-panel style={{ width: LOADER_PANEL_PX }} className="absolute inset-y-0 right-0 z-20 flex flex-col border-l border-border/60 bg-background/95 backdrop-blur-xl">
                    <div className="flex items-center justify-between border-b border-border/60 p-2">
                        <span className="px-2 text-xs font-medium">Loader</span>
                        <button type="button" data-loader-close aria-label="Close the Loader panel" onClick={() => setLoaderOpen(false)}
                            className="rounded px-2 py-1 text-xs text-muted-foreground hover:bg-accent">×</button>
                    </div>
                    <div className="min-h-0 flex-1 overflow-y-auto"><FactoryLoader snapshot={snapshot ?? null} controls={controls} /></div>
                </aside>
            )}
            <AgentPanel />
            <ControlCenter />
        </div>
    )
}
