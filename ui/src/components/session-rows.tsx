import { Link } from '@tanstack/react-router'

import type { RuntimeSession, SessionList, SessionRun, SessionsProgress } from '@/api/types'
import { Age } from '@/components/age'
import { ChoreRunLink } from '@/components/chore-link'
import { Copyable } from '@/components/copy-button'
import { Cost } from '@/components/cost'
import { EpicLink } from '@/components/epic-link'
import { Mark, MarkedText } from '@/components/marked-text'
import { ReviewLink } from '@/components/review-link'
import { ListRow, RowLine } from '@/components/rows'
import { RunLink } from '@/components/run-link'
import { Chip } from '@/components/status'
import { TaskRunLink } from '@/components/task-link'
import { TickLink } from '@/components/tick-link'
import { Timestamp } from '@/components/timestamp'
import { Tip } from '@/components/tip'
import { sessionModels } from '@/lib/models'
import { directoryTail, moreMessages, sessionName, unstopped } from '@/lib/sessions'
import { byteSize } from '@/lib/ticks'
import { cn } from '@/lib/utils'

/** What `indexed in part` means, in its tip. */
const CUT_MEANS = 'It is longer than the index reads of one session, so words past that are not found.'

/** No words to mark: a list read without any. */
const NO_WORDS: readonly string[] = []

/**
 * The runtime's sessions as rows of a `RowList` of kind `session`, each subagent's right under the session it ran for,
 * marked `subagent`. A title is untrusted text, shown as text with `words` marked, and so is the snippet under the
 * title of one found by what it said, with what else the hit says: how many more of its messages hold the words, and
 * whether it was indexed in part. With `narrow`, a row's directory links the Sessions page narrowed to the sessions
 * that ran there, keeping the page's other flags. With `costly`, for a list held to a cost, each row's cost reads in
 * the foreground: it is what the list was narrowed by.
 */
export function SessionRows({
    sessions,
    words = NO_WORDS,
    narrow = false,
    costly = false,
}: {
    sessions: readonly RuntimeSession[]
    words?: readonly string[]
    narrow?: boolean
    costly?: boolean
}) {
    return sessions.map((s) => (
        <SessionRow key={s.session_id} session={s} words={words} parent={null} narrow={narrow} costly={costly} />
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
            {progress.error !== null && <>, which failed: {unstopped(progress.error)}</>}
            {!progress.current &&
                ". Titles are not yet read as sessions.exclude says: the loop's next wait reads them from the first"}
            .
        </>
    )
}

/**
 * How far the index of what sessions said has read the runtime's record, in a line that leads with what the operator
 * needs first: that it is still being built, and how far back it has got, or once built what it holds and up to when;
 * then its size and when it was last read, or why that failed. Why `text` finds by titles alone, where the runtime or
 * SQLite cannot keep the index; nothing below `text`.
 */
export function SessionsIndexLine({ list }: { list: Pick<SessionList, 'search' | 'index' | 'why_titles'> }) {
    if (list.why_titles !== null) {
        return list.why_titles
    }
    if (list.search !== 'text') {
        return null
    }
    const { index } = list
    if (index === null) {
        return <>The index of what sessions said is not built yet: the loop&apos;s waits between ticks build it.</>
    }
    if (index.read_at === null) {
        return (
            <>
                The index of what sessions said is new: the loop&apos;s next wait reads the runtime&apos;s sessions into
                it.
            </>
        )
    }
    const sessions = `${index.sessions} ${index.sessions === 1 ? 'session' : 'sessions'}`
    return (
        <>
            {index.built ? (
                <>
                    The index holds what {sessions} said
                    {index.through !== null && (
                        <>
                            , up to <Timestamp at={index.through} />
                        </>
                    )}
                </>
            ) : (
                <>
                    Still indexing what sessions said: {sessions} so far
                    {index.back_to !== null && (
                        <>
                            , back to <Timestamp at={index.back_to} />
                        </>
                    )}
                </>
            )}{' '}
            ({byteSize(index.size_bytes)}); last read <Age at={index.read_at} variant="ago" />
            {index.error !== null && <>, which failed: {unstopped(index.error)}</>}
            {!index.current && ". It is not yet built as sessions.exclude says: the loop's next wait builds it again"}.
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
    costly,
}: {
    session: RuntimeSession
    words: readonly string[]
    parent: string | null
    narrow: boolean
    costly: boolean
}) {
    const name = sessionName(session)
    const models = sessionModels(session.asked, session.models)
    const snippet = session.snippet !== null && session.snippet.length > 0 ? session.snippet : null
    const more = moreMessages(session.more_messages)
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
                <Cost
                    usd={session.cost_usd}
                    className={cn('text-right text-xs', costly ? 'text-foreground' : 'text-muted-foreground')}
                />
                <Age at={session.started_at} variant="ago" className="text-right" />
                {(snippet !== null || more !== null || session.cut) && (
                    <RowLine from="title">
                        {/* Why it was found, as one line of reading: the snippet, then what else the hit says. Text,
                            never markup; its URLs are not linked, since a snippet may cut one short. */}
                        <p className="text-sm wrap-break-word text-muted-foreground">
                            {snippet !== null && (
                                <span data-testid="session-snippet">
                                    {/* A snippet's pieces never reorder, so their index is their key. */}
                                    {snippet.map((part, i) =>
                                        part.marked ? <Mark key={i}>{part.text}</Mark> : part.text,
                                    )}
                                </span>
                            )}
                            {/* A dot that stays with the snippet's end, so a note that wraps starts its line clean. */}
                            {snippet !== null && (more !== null || session.cut) && ' · '}
                            {(more !== null || session.cut) && (
                                <span className="text-xs" data-testid="session-hit-note">
                                    {/* Each piece keeps to one line; the two may part where the row is narrow. */}
                                    {more !== null && <span className="whitespace-nowrap">{more}</span>}
                                    {more !== null && session.cut && ' · '}
                                    {session.cut && (
                                        <Tip fact="indexed in part" detail={CUT_MEANS}>
                                            <span
                                                className={cn(
                                                    'whitespace-nowrap',
                                                    'underline decoration-dotted underline-offset-4',
                                                )}
                                            >
                                                indexed in part
                                            </span>
                                        </Tip>
                                    )}
                                </span>
                            )}
                        </p>
                    </RowLine>
                )}
                {models !== null && (
                    <RowLine from="title">
                        <span className="font-mono text-xs text-muted-foreground" data-testid="session-models">
                            {models}
                        </span>
                    </RowLine>
                )}
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
                <SessionRow
                    key={s.session_id}
                    session={s}
                    words={words}
                    parent={name}
                    narrow={narrow}
                    costly={costly}
                />
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
