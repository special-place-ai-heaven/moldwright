'use client'

import { IsoGrid } from '@rerun/ui/iso-grid'
import { useEffect, useMemo, useRef, useState } from 'react'

import { fireRerunConfetti } from '@/lib/confetti'
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip'
import { METRICS, type MetricDef, type MetricKey, type MetricValues } from './factory-metrics'
import { LOOP_MS, factoryScene } from './factory-scene'

const TICK_MS = 100
// shortcut: one second of the sample loop stands for half a minute of a real wave.
const SAMPLE_SCALE = 30

const median = (xs: number[]) => { const s = [...xs].sort((a, b) => a - b); return s.length ? s[Math.floor(s.length / 2)] : 0 }

// The factory, drawn by the board's own world. The world takes the whole stage; a thin glass bar
// carries the gauges and the counts, and a band drops in while sending is held.
export function FactoryWorld({ theme = 'light' }: { theme?: 'light' | 'dark' }) {
    const [clock, setClock] = useState(() => ({ start: Date.now(), now: Date.now() }))
    const [expired, setExpired] = useState<Set<string>>(() => new Set())
    useEffect(() => {
        const id = setInterval(() => setClock(c => ({ ...c, now: Date.now() })), TICK_MS)
        return () => clearInterval(id)
    }, [])

    const t = (clock.now - clock.start) % LOOP_MS
    const frame = useMemo(() => factoryScene(t, clock.now), [t, clock.now])
    // Two bubbles at most, the newest: more read as noise.
    const toasts = frame.toasts.filter(toast => !expired.has(toast.id)).slice(-2)

    // A merge throws the app's own confetti.
    const merged = useRef(frame.counts.merged)
    useEffect(() => {
        if (frame.counts.merged > merged.current) void fireRerunConfetti()
        merged.current = frame.counts.merged
    }, [frame.counts.merged])

    const signInMin = Math.max(0, 412 - Math.floor((clock.now - clock.start) / 60_000))
    const realMin = (ms: number) => (ms * SAMPLE_SCALE) / 60_000
    const values: MetricValues = {
        intake: { text: String(frame.counts.waiting) },
        building: { text: String(frame.counts.building) },
        review: { text: String(frame.counts.review) },
        checks: { text: String(frame.counts.checks) },
        shipped: { text: String(frame.counts.merged) },
        copies: { text: `${frame.copies.code}/6 · ${frame.copies.LINUS}/3 · ${frame.copies.search}/3`, fill: (frame.copies.code / 6) * 100 },
        leadTime: { text: frame.leadMs.length ? `${realMin(median(frame.leadMs)).toFixed(0)} min` : '–' },
        throughput: { text: frame.counts.merged && t ? (frame.counts.merged / (realMin(t) / 60)).toFixed(1) : '–' },
        firstPass: { text: frame.counts.merged ? '100%' : '–' },
        blocked: { text: '0' },
        planWeek: { text: '56%', fill: 56 },
        tokensPerJob: { text: '312k' },
        signIn: frame.held ? { text: 'renewing', fill: 2, warn: true } : { text: `${signInMin} min`, fill: Math.min(100, (signInMin / 480) * 100) },
    }

    return (
        <div className={`${theme} relative h-dvh w-full overflow-hidden bg-background text-foreground`}>
            <IsoGrid
                tiles={frame.tiles}
                containers={frame.containers}
                liveLinks={frame.links}
                toasts={toasts}
                onToastExpire={id => setExpired(prev => new Set(prev).add(id))}
                fitToContent
                showLinks
                selectedTileId={null}
                scrollGestures
            />

            <div className="pointer-events-none absolute inset-x-0 bottom-0 flex justify-center p-5">
                <div className="pointer-events-auto flex items-stretch gap-4 rounded-2xl border border-border/60 bg-background/75 px-5 py-3 shadow-[0_8px_40px_rgba(0,0,0,0.12)] backdrop-blur-xl">
                    <div className="flex items-center gap-2 pr-1">
                        <span className={`size-2 rounded-full ${frame.held ? 'bg-red-500' : 'animate-pulse bg-emerald-500'}`} />
                        <span className="text-sm font-semibold tracking-tight">Factory</span>
                        <span className="text-[10px] text-muted-foreground">sample</span>
                    </div>
                    {(['now', 'today', 'cost'] as const).map(group => (
                        <div key={group} className="flex items-center gap-4 border-l border-border/70 pl-4">
                            {METRICS.filter(m => m.group === group).map(m => <Metric key={m.key} def={m} value={values[m.key]} />)}
                        </div>
                    ))}
                </div>
            </div>

            <div
                className="pointer-events-none absolute inset-x-0 top-6 flex justify-center transition-all duration-500"
                style={{ opacity: frame.held ? 1 : 0, transform: frame.held ? 'translateY(0)' : 'translateY(-12px)' }}
            >
                <div className="flex items-center gap-3 rounded-full border border-red-500/40 bg-red-500/15 px-4 py-1.5 text-sm text-red-600 shadow-[0_0_24px_rgba(239,68,68,0.35)] backdrop-blur-xl dark:text-red-300">
                    <span className="font-semibold">Line held</span>
                    <span>sign-in renewal · {Math.ceil(frame.holdLeftMs / 1000)} s left · running builds finish</span>
                </div>
            </div>
        </div>
    )
}

const TONES: Partial<Record<MetricKey, string>> = { building: 'text-amber-500', review: 'text-emerald-500', checks: 'text-indigo-500', shipped: 'text-green-500' }

function Metric({ def, value }: { def: MetricDef; value: MetricValues[MetricKey] }) {
    return (
        <Tooltip>
            <TooltipTrigger asChild>
                <div className="flex cursor-help flex-col items-center justify-center leading-none" tabIndex={0}>
                    <span className={`font-mono text-base font-semibold tabular-nums ${value.warn ? 'text-red-500' : (TONES[def.key] ?? 'text-foreground')}`}>{value.text}</span>
                    {value.fill !== undefined && (
                        <span className="mt-1 h-1 w-14 overflow-hidden rounded-full bg-muted">
                            <span className={`block h-full rounded-full transition-all duration-700 ${value.warn ? 'bg-red-500' : 'bg-[#4d34f7]'}`} style={{ width: `${value.fill}%` }} />
                        </span>
                    )}
                    <span className="mt-1 text-[10px] uppercase tracking-wider text-muted-foreground">{def.label}</span>
                </div>
            </TooltipTrigger>
            <TooltipContent className="max-w-64">
                <p>{def.definition}</p>
                <p className="mt-1 opacity-70">Source: {def.source}</p>
            </TooltipContent>
        </Tooltip>
    )
}
