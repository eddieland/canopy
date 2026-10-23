import { useQuery } from '@tanstack/react-query'

import { ApiError } from '@/api/client'
import { taskReportQuery } from '@/api/queries'
import type { TaskRun, TaskSummary } from '@/api/types'
import { CopyablePath } from '@/components/copy-button'
import { Empty, Panel, PanelHeader, PanelLoading } from '@/components/panel'
import { PlanDocument } from '@/components/plan-editor'
import { Chip } from '@/components/status'
import { taskRunRef } from '@/lib/refs'
import { noReport, reportRun } from '@/lib/tasks'

// What the `edited` chip means, on hover and to a screen reader.
const EDITED = 'Edited since its run left it: this is the file as it stands now, which its next run reads.'

/**
 * A task's report (DESIGN §36), the page's main content: the newest one a run left, as its file stands now, laid out
 * as a document through the plan's schema, so what the agent wrote stays text. Its header names the run that left it,
 * and `edited` once the file changed since. A task no run has reported on says what comes next; a file no longer a
 * report says why, as `canopy show task:N` does.
 */
export function TaskReportPanel({
    task,
    runs,
    className,
}: {
    /** The task. */
    task: TaskSummary
    /** Its runs, the oldest first. */
    runs: readonly TaskRun[]
    /** Classes for the panel, such as its place in the page's grid. */
    className?: string
}) {
    const run = reportRun(runs)
    const query = useQuery({ ...taskReportQuery(task.id, run?.id ?? 0), enabled: run !== undefined })
    const { data, error } = query
    const ref = run === undefined ? undefined : taskRunRef(task.id, run.id)
    return (
        <Panel className={className} data-testid="task-report">
            <PanelHeader label="Report">
                {ref !== undefined && (
                    <span className="flex items-center gap-2">
                        {/* A file no longer a report reads as edited too: its problem says it, not this chip. */}
                        {data?.edited === true && data.text !== null && (
                            <span title={EDITED} className="inline-flex">
                                <Chip>edited</Chip>
                                <span className="sr-only">{EDITED}</span>
                            </span>
                        )}
                        <span className="readout text-xs text-muted-foreground">from {ref}</span>
                    </span>
                )}
            </PanelHeader>
            {run === undefined || (error instanceof ApiError && error.status === 404) ? (
                <Empty size="panel">{run === undefined ? noReport(task, runs) : 'no report: its run left none'}</Empty>
            ) : data === undefined ? (
                <PanelLoading query={query} rows={4} className="min-h-72" />
            ) : data.text === null ? (
                <Empty size="panel">no report to read: its file is {data.problem ?? 'unreadable'}</Empty>
            ) : (
                <>
                    {/* A new hash is new text: the document reads its Markdown once. */}
                    <PlanDocument key={data.sha256 ?? ''} markdown={data.text} label={`Report from ${ref ?? ''}`} />
                    <p className="border-t px-3 py-2 font-mono text-xs text-muted-foreground">
                        <CopyablePath path={data.path} label="report path" />
                    </p>
                </>
            )}
        </Panel>
    )
}
