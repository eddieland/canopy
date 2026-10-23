import type { TaskRun, TaskSummary, TaskTicket } from '@/api/types'
import { Copyable } from '@/components/copy-button'
import { Field, Fields } from '@/components/fields'
import { LinkOut } from '@/components/link-out-icon'
import { None } from '@/components/none'
import { Panel, PanelHeader } from '@/components/panel'
import { PullRequestLink } from '@/components/pull-request-link'
import { TicketLink } from '@/components/ticket-link'
import { Tip } from '@/components/tip'
import { useBranchUrls } from '@/hooks/use-branch-urls'
import { taskRunRef } from '@/lib/refs'
import { shortSha } from '@/lib/reviews'
import { taskPrs } from '@/lib/tasks'

/** What the panel's foot says of everything above it, on every task (DESIGN §36). */
export const THROWAWAY = 'All of it is throwaway until you give it a pass of its own.'

/**
 * What a task's runs left (DESIGN §36): its repository; its branch, with a link out once a run pushed to it; each
 * run's pushed head commit, the exact commit a ticket would cite after later runs move the branch, with a copy
 * button; the draft PR its runs named; and the tickets they filed, unlabeled, each opening its page. Under them, one
 * plain line: none of it is more than a first draft until the operator gives it a pass.
 */
export function TaskLeft({
    task,
    runs,
    tickets,
    className,
}: {
    /** The task. */
    task: TaskSummary
    /** Its runs, the oldest first. */
    runs: readonly TaskRun[]
    /** The tickets its runs filed, the oldest first. */
    tickets: readonly TaskTicket[]
    /** Classes for the panel, such as its place in the page's grid. */
    className?: string
}) {
    const branchUrl = useBranchUrls()
    const pushed = runs.filter((run) => run.head !== null)
    // The branch is on its host only once a run pushed it.
    const href = pushed.length > 0 ? branchUrl(task.repo, task.branch) : undefined
    const prs = taskPrs(runs)
    return (
        <Panel className={className} data-testid="task-left">
            <PanelHeader label="What it left" />
            <Fields>
                <Field label="repository" mono>
                    {task.repo}
                </Field>
                <Field label="branch" mono>
                    <span className="inline-flex max-w-full min-w-0 items-center gap-1">
                        <Copyable text={task.branch} label="branch" />
                        {href !== undefined && <LinkOut href={href} label={`${task.branch} in ${task.repo}`} />}
                    </span>
                </Field>
                <Field label="commits" mono>
                    {pushed.length === 0 ? (
                        <None reason="nothing pushed" />
                    ) : (
                        <ul className="flex flex-col gap-1" data-testid="task-heads">
                            {pushed.map((run) => (
                                <Head key={run.id} task={task.id} run={run} />
                            ))}
                        </ul>
                    )}
                </Field>
                <Field label="draft PR" mono>
                    {prs.length === 0 ? (
                        <None />
                    ) : (
                        <span className="flex flex-wrap gap-x-3 gap-y-1">
                            {prs.map((pr) => (
                                <PullRequestLink key={pr} url={pr} />
                            ))}
                        </span>
                    )}
                </Field>
                <Field label={task.project === null ? 'tickets' : `tickets in ${task.project}`} mono>
                    {tickets.length === 0 ? (
                        <None reason={task.project === null ? 'it names no project' : undefined} />
                    ) : (
                        <ul className="flex flex-col gap-1" data-testid="task-tickets">
                            {tickets.map((ticket) => (
                                <li key={ticket.key} className="flex items-center gap-2">
                                    <TicketLink ticketKey={ticket.key} />
                                    <span className="text-muted-foreground">
                                        from {taskRunRef(task.id, ticket.run_id)}
                                    </span>
                                </li>
                            ))}
                        </ul>
                    )}
                </Field>
            </Fields>
            <p className="border-t px-3 py-2 text-xs text-muted-foreground">{THROWAWAY}</p>
        </Panel>
    )
}

/** One run's pushed head: its run, then the commit's first 7 characters, the whole hash on hover and copied whole. */
function Head({ task, run }: { task: number; run: TaskRun }) {
    const head = run.head ?? ''
    return (
        <li className="flex items-center gap-2">
            <span className="text-muted-foreground">{taskRunRef(task, run.id)}</span>
            <Copyable text={head} label="commit">
                <Tip fact={head} mono>
                    <span className="readout">{shortSha(head)}</span>
                </Tip>
            </Copyable>
        </li>
    )
}
