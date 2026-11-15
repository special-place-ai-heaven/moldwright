'use client'

import { useSearchParams } from 'next/navigation'
import { FactoryWorld } from '@/components/factory/FactoryWorld'

// Temporary lab: the factory world on sample data, for capture on a local machine. Removed before
// the commit; the real page lives under (dashboard).
export default function FactoryLab() {
    const theme = useSearchParams().get('theme') === 'light' ? 'light' : 'dark'
    return <FactoryWorld theme={theme} />
}
