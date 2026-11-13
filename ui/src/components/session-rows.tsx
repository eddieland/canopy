import { Link } from '@tanstack/react-router'

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
import { directoryTail, sessionName } from '@/lib/sessions'

/** No words to mark: a list read without any. */
const NO_WORDS: readonly string[] = []

/**
 * The runtime's sessions as rows of a `RowList` of kind `session`, each subagent's right under the session it ran for,
 * marked `subagent`. A title is untrusted text, shown as text with `words` marked. With `narrow`, a row's directory
 * links the Sessions page narrowed to the sessions that ran there, keeping the page's other flags.
 */
export function SessionRows({
    sessions,
    words = NO_WORDS,
    narrow = false,
}: {
    sessions: readonly RuntimeSession[]
    words?: readonly string[]
    narrow?: boolean
}) {
    return sessions.map((s) => (
        <SessionRow key={s.session_id} session={s} words={words} parent={null} narrow={narrow} />
    ))
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

/**
 * A session's row, then its subagents' rows right under it. Every title starts at the same place, so the column reads
 * straight; the `subagent` chip says a row ran for the one above, and names that session to a screen reader.
 */
function SessionRow({
    session,
    words,
    parent,
    narrow,
}: {
    session: RuntimeSession
    words: readonly string[]
    parent: string | null
    narrow: boolean
}) {
    const name = sessionName(session)
    return (
        <>
            {/* `group/copy`: the command's copy button shows while the pointer is anywhere over the row. */}
            <ListRow kind="session" className="group/copy items-baseline" data-testid="session">
                <span className="flex min-w-0">
                    <Where session={session} narrow={narrow} />
                </span>
                <span className="flex min-w-0 gap-1">
                    {session.parent_id !== null && (
                        <Chip>
                            subagent<span className="sr-only"> of {parent ?? `session ${session.parent_id}`}</span>
                        </Chip>
                    )}
                    {session.archived && <Chip>archived</Chip>}
                </span>
                {/* In medium weight, as a run's title is, so it reads as the row's name. */}
                <span className="min-w-0 truncate text-sm font-medium">
                    {session.title === null ? (
                        <span className="font-normal text-muted-foreground">no title</span>
                    ) : (
                        <MarkedText text={session.title} words={words} />
                    )}
                </span>
                <Cost usd={session.cost_usd} className="text-right text-xs text-muted-foreground" />
                <Age at={session.started_at} variant="ago" className="text-right" />
                {session.reopen !== null && (
                    <RowLine from="title">
                        <Copyable
                            text={session.reopen}
                            label={`reopen command of ${name}`}
                            reveal
                            words
                            className="font-mono text-xs text-muted-foreground"
                        />
                    </RowLine>
                )}
            </ListRow>
            {session.subagents.map((s) => (
                <SessionRow key={s.session_id} session={s} words={words} parent={name} narrow={narrow} />
            ))}
        </>
    )
}

/**
 * Where a session opens: the page of the run of canopy's that made it, or, for one outside canopy or one no run
 * names, the end of the directory it ran in, the whole on hover, so the title beside it keeps the width. With
 * `narrow`, the directory links the Sessions page narrowed to it.
 */
function Where({ session, narrow }: { session: RuntimeSession; narrow: boolean }) {
    if (session.made_by !== null) {
        return <RunOf run={session.made_by} />
    }
    const tail = directoryTail(session.directory)
    if (!narrow) {
        return (
            <Tip fact={session.directory} mono>
                <span className="truncate font-mono text-xs text-muted-foreground">{tail}</span>
            </Tip>
        )
    }
    return (
        <Tip fact={session.directory} mono detail="narrows the list to it">
            <Link
                to="/workspace/sessions"
                search={(prev) => ({ ...prev, directory: session.directory })}
                className="truncate font-mono text-xs text-muted-foreground underline-offset-4 hover:underline"
            >
                {tail}
            </Link>
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
