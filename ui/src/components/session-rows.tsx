import type { SessionsProgress, RuntimeSession, SessionRun } from '@/api/types'
import { Age } from '@/components/age'
import { ChoreRunLink } from '@/components/chore-link'
import { Copyable } from '@/components/copy-button'
import { Cost } from '@/components/cost'
import { EpicLink } from '@/components/epic-link'
import { MarkedText } from '@/components/marked-text'
import { ReviewLink } from '@/components/review-link'
import { ListRow, RowLine } from '@/components/rows'
import { RunLink } from '@/components/run-link'
import { Chip } from '@/components/status'
import { TaskRunLink } from '@/components/task-link'
import { TickLink } from '@/components/tick-link'
import { Timestamp } from '@/components/timestamp'
import { Tip } from '@/components/tip'

/** No words to mark: a list read without any. */
const NO_WORDS: readonly string[] = []

/**
 * The runtime's sessions as rows of a `RowList` of kind `session`, each subagent's under the session it ran for and
 * its title indented a step deeper. A title is untrusted text, shown as text with `words` marked.
 */
export function SessionRows({
    sessions,
    words = NO_WORDS,
}: {
    sessions: readonly RuntimeSession[]
    words?: readonly string[]
}) {
    return sessions.map((s) => <SessionRow key={s.session_id} session={s} words={words} depth={0} />)
}

/**
 * How far the loop's read of the runtime's record has come, in a line under the list, as `canopy sessions` ends with
 * it: every session updated up to a moment was read, and when the last read was, or why it failed.
 */
export function SessionsProgressLine({ progress }: { progress: SessionsProgress }) {
    if (progress.read_at === null) {
        return (
            <>canopy loop has not read the runtime&apos;s sessions yet: it reads them while it waits between ticks.</>
        )
    }
    return (
        <>
            {progress.through === null ? (
                'No session read yet'
            ) : (
                <>
                    Read every session updated up to <Timestamp at={progress.through} />
                </>
            )}
            ; last read <Age at={progress.read_at} variant="ago" />
            {progress.error !== null && <>, which failed: {progress.error}</>}
            {!progress.current &&
                ". Titles are not yet read as sessions.exclude says: the loop's next wait reads them from the first"}
            .
        </>
    )
}

/** A session's row, then its subagents' under it, a step deeper. */
function SessionRow({ session, words, depth }: { session: RuntimeSession; words: readonly string[]; depth: number }) {
    return (
        <>
            <ListRow kind="session" className="items-baseline" data-testid="session">
                <span className="flex min-w-0">
                    <Where session={session} />
                </span>
                <span className="flex min-w-0 gap-1">
                    {session.parent_id !== null && <Chip>subagent</Chip>}
                    {session.archived && <Chip>archived</Chip>}
                </span>
                {/* Indented a step for each session it ran for, so a subagent's reads as under its parent's. */}
                <span className="min-w-0 truncate text-sm" style={{ paddingInlineStart: `${depth}rem` }}>
                    {session.title === null ? (
                        <span className="text-muted-foreground">no title</span>
                    ) : (
                        <MarkedText text={session.title} words={words} />
                    )}
                </span>
                <Cost usd={session.cost_usd} className="text-right text-xs text-muted-foreground" />
                <Age at={session.started_at} variant="ago" className="text-right" />
                {session.reopen !== null && (
                    <RowLine from="title" style={{ paddingInlineStart: `${depth}rem` }}>
                        <Copyable
                            text={session.reopen}
                            label="reopen command"
                            reveal
                            className="font-mono text-xs text-muted-foreground"
                        />
                    </RowLine>
                )}
            </ListRow>
            {session.subagents.map((s) => (
                <SessionRow key={s.session_id} session={s} words={words} depth={depth + 1} />
            ))}
        </>
    )
}

/**
 * Where a session opens: the page of the run of canopy's that made it, or, for one outside canopy or one no run
 * names, the directory it ran in, cut to fit and whole on hover.
 */
function Where({ session }: { session: RuntimeSession }) {
    if (session.made_by !== null) {
        return <RunOf run={session.made_by} />
    }
    return (
        <Tip fact={session.directory} mono whenCut>
            <span className="truncate font-mono text-xs text-muted-foreground">{session.directory}</span>
        </Tip>
    )
}

/** The page of the run that made a session: a tick's, a run's, a review's, a chore run's, a task run's, an epic's. */
function RunOf({ run }: { run: SessionRun }) {
    switch (run.kind) {
        case 'tick': {
            return <TickLink id={run.id} />
        }
        case 'run': {
            return <RunLink id={run.id} />
        }
        case 'review': {
            return <ReviewLink id={run.id} />
        }
        case 'chore_run': {
            return run.chore === null ? null : <ChoreRunLink name={run.chore} id={run.id} />
        }
        case 'task_run': {
            return run.task_id === null ? null : <TaskRunLink task={run.task_id} run={run.id} />
        }
        case 'epic_run': {
            return run.epic_id === null ? null : <EpicLink id={run.epic_id} />
        }
    }
}
