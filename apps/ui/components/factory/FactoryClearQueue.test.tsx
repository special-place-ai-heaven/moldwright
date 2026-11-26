// @vitest-environment happy-dom
import { act, createElement } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { FactorySnapshot } from '@moldwright/contracts'

const mocks = vi.hoisted(() => ({ clearFactoryQueueAction: vi.fn() }))

vi.mock('@/app/api/_actions/factory.actions', () => ({ clearFactoryQueueAction: mocks.clearFactoryQueueAction }))
vi.mock('./use-factory-controls', () => ({ thrown: () => ({ ok: false }) }))
vi.mock('@/hooks/useErrorText', () => ({ useErrorText: () => () => 'error' }))
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }))
vi.mock('next-intl', () => ({ useTranslations: () => (key: string, values?: object) => values ? `${key} ${JSON.stringify(values)}` : key }))
vi.mock('@/components/dialogs/ConfirmDialog', () => ({
    ConfirmDialog: ({ open, title, onConfirm }: { open: boolean; title: string; onConfirm: () => void }) => open ? createElement('button', { 'data-confirm': '', onClick: onConfirm }, title) : null,
}))

let root: Root | null = null
let container: HTMLElement | null = null

afterEach(() => {
    act(() => root?.unmount())
    root = null
    container?.remove()
})

describe('FactoryClearQueue', () => {
    it('clears and reports the project it was asked for when the factory switches projects', async () => {
        mocks.clearFactoryQueueAction.mockResolvedValue({ ok: true, id: 'qc-1', count: 2 })
        const { FactoryClearQueue } = await import('./FactoryClearQueue')
        const controls = { view: { isOwner: true }, reload: vi.fn().mockResolvedValue(undefined) } as never
        const render = (snapshot: object, issues: number[]) => root!.render(createElement(FactoryClearQueue, { snapshot: snapshot as FactorySnapshot, controls, issues }))
        container = document.createElement('div')
        document.body.appendChild(container)
        root = createRoot(container)
        const status = () => container!.querySelector('[role="status"]')!.textContent
        const button = () => container!.querySelector<HTMLButtonElement>('[data-clear-queue-button]')!

        await act(async () => render({ repo: 'acme/a' }, [5, 6]))
        await act(async () => button().click())
        await act(async () => render({ repo: 'acme/b' }, [9]))
        const confirm = container!.querySelector<HTMLButtonElement>('[data-confirm]')!
        expect(confirm.textContent).toContain('"repo":"acme/a"')
        expect(confirm.textContent).toContain('"count":2')
        await act(async () => confirm.click())
        expect(mocks.clearFactoryQueueAction).toHaveBeenCalledWith('acme/a', [5, 6])
        expect(status()).toBe('queueClearWaiting {"repo":"acme/a"}')

        await act(async () => render({ repo: 'acme/b', queue_clear: { id: 'qc-1', repo: 'acme/a', outcome: 'wrong_project', cleared: [], kept: [], at: '2026-11-25T19:00:00Z' } }, [9]))
        expect(status()).toBe('queueClearRefusedProject {"repo":"acme/a"}')
        expect(button().getAttribute('aria-disabled')).toBeNull()

        await act(async () => render({ repo: 'acme/b', queue_clear: { id: 'qc-0', repo: 'acme/c', outcome: 'cleared', cleared: [1], kept: [], at: '2026-11-25T18:00:00Z' } }, [9]))
        expect(status()).toBe('')
        expect(button().getAttribute('aria-disabled')).toBeNull()
    })
})
