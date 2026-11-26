'use client'

import { useEffect, useRef, useState } from 'react'
import { useTranslations } from 'next-intl'
import { toast } from 'sonner'
import { FACTORY_QUEUE_CLEAR_WAIT_S, type FactorySnapshot } from '@moldwright/contracts'
import { clearFactoryQueueAction } from '@/app/api/_actions/factory.actions'
import { ConfirmDialog } from '@/components/dialogs/ConfirmDialog'
import { Button } from '@/components/ui/button'
import { useErrorText } from '@/hooks/useErrorText'
import { thrown, type FactoryControlsState } from './use-factory-controls'

type Ask = { repo: string; issues: number[] }

export function FactoryClearQueue({ snapshot, controls, issues }: { snapshot: FactorySnapshot; controls: FactoryControlsState; issues: number[] }) {
    const t = useTranslations('factory.controls')
    const errorText = useErrorText()
    const [confirming, setConfirming] = useState(false)
    const [ask, setAsk] = useState<Ask>({ repo: '', issues: [] })
    const [busy, setBusy] = useState(false)
    const [sent, setSent] = useState<{ id: string; repo: string; answered: boolean } | null>(null)
    const [expired, setExpired] = useState(false)
    const ref = useRef<HTMLButtonElement>(null)

    useEffect(() => {
        if (sent === null) return
        const timer = setTimeout(() => setExpired(true), FACTORY_QUEUE_CLEAR_WAIT_S * 1000)
        return () => clearTimeout(timer)
    }, [sent])

    if (sent !== null && !sent.answered && snapshot.queue_clear?.id === sent.id) setSent({ ...sent, answered: true })

    if (controls.view?.isOwner !== true) return null
    const repo = snapshot.repo
    const report = snapshot.queue_clear && (snapshot.queue_clear.repo === repo || snapshot.queue_clear.id === sent?.id) ? snapshot.queue_clear : undefined
    const unanswered = sent !== null && !sent.answered && report?.id !== sent.id
    const waiting = unanswered && !expired
    const off = repo === null || issues.length === 0 || busy || waiting
    const status = unanswered ? t(waiting ? 'queueClearWaiting' : 'queueClearUnconfirmed', { repo: sent.repo })
        : report?.outcome === 'wrong_project' ? t('queueClearRefusedProject', { repo: report.repo })
        : report?.outcome === 'expired' ? t('queueClearExpired', { repo: report.repo })
        : report ? t('queueClearReport', { repo: report.repo, cleared: report.cleared.length, kept: report.kept.length }) : null

    const closeConfirm = (keep: boolean) => {
        if (keep) return
        setConfirming(false)
        requestAnimationFrame(() => ref.current?.focus())
    }
    const clear = async (frozen: Ask) => {
        setBusy(true)
        const res = await clearFactoryQueueAction(frozen.repo, frozen.issues).catch(thrown)
        if (!res.ok) toast.error(errorText(res))
        else {
            setExpired(false)
            setSent({ id: res.id, repo: frozen.repo, answered: false })
            toast.success(t('queueClearSent', { count: res.count }))
            await controls.reload()
        }
        setBusy(false)
    }

    return (
        <div data-clear-queue className="flex items-center justify-between gap-2">
            <span role="status" aria-live="polite" className="text-xs text-muted-foreground">
                {status}
            </span>
            <Button ref={ref} type="button" size="xs" variant="ghost" className="text-destructive aria-disabled:cursor-not-allowed aria-disabled:opacity-50" data-clear-queue-button
                aria-disabled={off || undefined} aria-busy={busy} onClick={() => { if (off || repo === null) return; setAsk({ repo, issues }); setConfirming(true) }}>
                {t('clearQueue')}
            </Button>
            <ConfirmDialog
                open={confirming}
                onOpenChange={closeConfirm}
                title={t('confirmClearQueueTitle', { count: ask.issues.length, repo: ask.repo })}
                description={t('confirmClearQueueBody')}
                confirmLabel={t('confirmClearQueue')}
                confirmVariant="destructive"
                onConfirm={() => { closeConfirm(false); void clear(ask) }}
            />
        </div>
    )
}
