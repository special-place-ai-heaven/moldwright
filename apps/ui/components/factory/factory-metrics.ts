// What the factory bar shows, each number with its definition and its source. The definitions are
// the contract for the real page: the sample frame fills them now, the delegator's ledger later.

export type MetricKey =
    | 'intake' | 'building' | 'review' | 'checks' | 'shipped'
    | 'copies' | 'leadTime' | 'throughput' | 'firstPass' | 'blocked'
    | 'planWeek' | 'tokensPerJob' | 'signIn'

export type MetricGroup = 'now' | 'today' | 'cost'

export type MetricDef = { key: MetricKey; group: MetricGroup; label: string; definition: string; source: string }

export const METRICS: MetricDef[] = [
    { key: 'intake', group: 'now', label: 'Intake', definition: 'Jobs taken from an issue labelled factory and not yet sent to a builder: waiting on another job, or queued for a free run.', source: 'ledger jobs in state waiting or queued' },
    { key: 'building', group: 'now', label: 'Building', definition: 'Build and fix runs out now, every copy counted.', source: 'ledger jobs in state building or fixing' },
    { key: 'review', group: 'now', label: 'Review', definition: 'Review runs out now, plus pull requests waiting for a free reviewer.', source: 'ledger jobs in state reviewing or review wait' },
    { key: 'checks', group: 'now', label: 'Checks', definition: 'Approved pull requests waiting for the workflow runs of their head commit.', source: 'ledger jobs in state checks' },
    { key: 'shipped', group: 'now', label: 'Shipped', definition: 'Jobs merged into dev since 00:00 UTC.', source: 'ledger transitions to merged, today' },
    { key: 'copies', group: 'now', label: 'Copies', definition: 'Runs out now against the ceiling of each main coworker (code 6, LINUS 3, search 3).', source: 'ledger runs out, dispatch.json runs' },
    { key: 'leadTime', group: 'today', label: 'Lead time', definition: 'Median time from the label to the merge, over jobs merged today.', source: 'ledger: first transition to merged minus job taken' },
    { key: 'throughput', group: 'today', label: 'Per hour', definition: 'Merges in the last three hours, divided by three.', source: 'ledger transitions to merged' },
    { key: 'firstPass', group: 'today', label: 'First pass', definition: 'Share of jobs merged today that needed no fix round.', source: 'ledger: merged jobs with no fixing transition' },
    { key: 'blocked', group: 'today', label: 'Blocked', definition: 'Jobs that ended blocked, failed or returned today.', source: 'ledger end states, today' },
    { key: 'planWeek', group: 'cost', label: 'Plan week', definition: 'Share of the Claude plan weekly window used; it resets at the time shown.', source: 'engine list_ai_connections, plan windows' },
    { key: 'tokensPerJob', group: 'cost', label: 'Tokens / job', definition: 'Median total tokens of the build, review and fix runs of a job merged today.', source: 'engine run stats of the job runs' },
    { key: 'signIn', group: 'cost', label: 'Sign-in', definition: 'Minutes until the Claude sign-in expires. Below the run limit plus five minutes the delegator holds sending.', source: 'engine list_ai_connections, sign-in expiry' },
]

export type MetricValues = Record<MetricKey, { text: string; fill?: number; warn?: boolean }>
