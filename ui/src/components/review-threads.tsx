import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { Eraser, GitPullRequestDraft, Send, Undo2 } from 'lucide-react'
import { useId, useState } from 'react'

import { dropDraft, editDraft, refreshThreads, sendDrafts, stageDrafts } from '@/api/mutations'
import { pullRequestThreadsQuery } from '@/api/queries'
import type { Draft, FeedbackPlanItem, PullRequestThreads, Reaction, ReviewThread } from '@/api/types'
import { Age } from '@/components/age'
import { CommentText } from '@/components/comment-text'
import { DraftCardFrame, DraftForm, DraftVerbs, DropVerb, EditVerb } from '@/components/draft-card'
import { FeedbackPlanPanel, PlanProposal } from '@/components/feedback-plan'
import { LinkOut } from '@/components/link-out-icon'
import { MemoryText } from '@/components/memory-text'
import { Notice } from '@/components/notice'
import { Panel, PanelFooter, PanelHeader, PanelLoading } from '@/components/panel'
import { DiffPanels } from '@/components/review-diff'
import type { Wanted } from '@/components/review-diff'
import { ListRow } from '@/components/rows'
import { RunLink } from '@/components/run-link'
import { Chip, Word } from '@/components/status'
import { Button } from '@/components/ui/button'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import { useToast } from '@/hooks/use-toast'
import {
    DRAFT_TONE,
    REACTIONS,
    REACTION_LOOKS,
    draftAnchor,
    listDrafts,
    movedHead,
    open,
    placeThreads,
    reactionOf,
    staged,
    threadWhere,
    waiting,
} from '@/lib/drafts'
import type { Placed } from '@/lib/reviews'
import {
    draftDroppedText,
    draftEditedText,
    draftsSentText,
    draftsSentToast,
    draftsStagedText,
    draftsStagedToast,
} from '@/lib/outcomes'
import { shortSha } from '@/lib/reviews'
import { cn } from '@/lib/utils'

/**
 * A PR's review threads on the diff its latest run kept, each draft under the thread it answers (DESIGN §29, On the
 * PR's diff): what canopy's reader last read of the PR, never a worker's copy. A thread sits at its line, under its
 * file when the diff does not show the line or it is outdated, or in a Not in the diff panel. Its comments and every
 * draft are plain text, every hidden character named, a comment's `<details>` blocks folded. A draft is edited,
 * dropped, or sent where it sits; the head panel lists every draft with a link to its card, and sends every waiting one
 * together, as one comment review. The current feedback plan of the PR's ticket, when it has one, follows the head
 * panel, where it is approved, and each thread it covers carries its proposal above the drafts (DESIGN §32).
 */
export function ReviewThreads({ url }: { url: string }) {
    const client = useQueryClient()
    const query = useQuery(pullRequestThreadsQuery(url))
    // The file of the draft whose link the operator last followed, a new object each time, so the diff shows it.
    const [wanted, setWanted] = useState<Wanted | null>(null)
    const changed = () => void refreshThreads(client, url)
    const { data } = query
    if (data === undefined) {
        return (
            <Panel>
                <PanelHeader label="Review threads" />
                <PanelLoading query={query} rows={3} className="min-h-40" />
            </Panel>
        )
    }
    const placed = placeThreads(data)
    const proposals = new Map((data.feedback_plan?.items ?? []).map((i) => [i.thread_id, i]))
    return (
        <>
            <RepliesPanel threads={data} placed={placed} onChange={changed} onFollow={(file) => setWanted({ file })} />
            {data.feedback_plan !== null && <FeedbackPlanPanel plan={data.feedback_plan} onChange={changed} />}
            {data.diff !== null && (
                <DiffPanels
                    diff={data.diff}
                    placed={placed}
                    wanted={wanted}
                    cards={['thread', 'threads']}
                    renderCard={(t) => (
                        <ThreadCard key={t.id} thread={t} item={proposals.get(t.id)} onChange={changed} />
                    )}
                />
            )}
            {placed.elsewhere.length > 0 && (
                <Panel data-testid="threads-elsewhere">
                    <PanelHeader label={data.diff === null ? 'Threads' : 'Not in the diff'}>
                        <span className="readout text-xs text-muted-foreground">{placed.elsewhere.length}</span>
                    </PanelHeader>
                    <div className="flex flex-col gap-2 p-3">
                        {placed.elsewhere.map((t) => (
                            <ThreadCard key={t.id} thread={t} item={proposals.get(t.id)} onChange={changed} />
                        ))}
                    </div>
                </Panel>
            )}
            {data.unplaced.length > 0 && (
                <Panel data-testid="drafts-unplaced">
                    <PanelHeader label="Not on a thread">
                        <span className="readout text-xs text-muted-foreground">{data.unplaced.length}</span>
                    </PanelHeader>
                    <div className="flex flex-col gap-2 p-3">
                        {data.unplaced.map((d) => (
                            <DraftCard key={`${d.run}-${d.number}`} draft={d} onChange={changed} />
                        ))}
                    </div>
                </Panel>
            )}
        </>
    )
}

/**
 * The head of a PR's threads: how workers' comments reach GitHub now, when the reader last read the PR, a warning when
 * its head is past the diff the page shows, every draft with a link to its card, the drafts for the review's body, a
 * send of every waiting draft, and a stage of them in a pending review the operator submits on GitHub. While the PR
 * holds one, neither is offered: it says where to finish it. `onFollow` hears a link followed to a draft on a file,
 * by the file's index.
 */
function RepliesPanel({
    threads,
    placed,
    onChange,
    onFollow,
}: {
    threads: PullRequestThreads
    placed: Placed<ReviewThread>
    onChange: () => void
    onFollow: (file: number) => void
}) {
    const [said, setSaid] = useState<string | null>(null)
    const toast = useToast()
    const sendable = waiting(threads)
    const held = staged(threads)
    const send = useMutation({
        mutationFn: () => sendDrafts(sendable),
        onSuccess: (sent) => {
            setSaid(draftsSentText(sent))
            toast(draftsSentToast(sent))
            onChange()
        },
    })
    const stage = useMutation({
        mutationFn: () => stageDrafts(sendable),
        onSuccess: (sent) => {
            setSaid(draftsStagedText(sent))
            toast(draftsStagedToast(sent, threads.url))
            onChange()
        },
    })
    const busy = send.isPending || stage.isPending
    // GitHub keeps one pending review a person, so nothing else goes on the PR until that one is submitted or deleted.
    const offered = sendable.length > 0 && held.length === 0
    const moved = movedHead(threads)
    const count = threads.threads.length
    return (
        <Panel data-testid="review-replies">
            <PanelHeader label="Review threads">
                <span className="readout text-xs text-muted-foreground">
                    {count} {count === 1 ? 'thread' : 'threads'}
                </span>
            </PanelHeader>
            <div className="flex flex-col gap-2 p-3 text-sm">
                <p className="text-muted-foreground">
                    {threads.review_replies === 'approve' ? (
                        <>
                            Workers draft their replies, and nothing reaches the PR until you send it, as your own words
                            and unmarked: <code className="font-mono text-xs">trust.review_replies</code> is approve.
                        </>
                    ) : (
                        <>
                            Workers post their own replies, marked:{' '}
                            <code className="font-mono text-xs">trust.review_replies</code> is post. Drafts from runs
                            under approve can still be sent.
                        </>
                    )}{' '}
                    {threads.read_at === null ? (
                        'canopy has not read its threads yet.'
                    ) : (
                        <>
                            Read <Age at={threads.read_at} variant="ago" />
                            {threads.head_sha !== null && (
                                <>
                                    {' '}
                                    at <span className="font-mono text-xs">{shortSha(threads.head_sha)}</span>
                                </>
                            )}
                            .
                        </>
                    )}
                </p>
                {moved !== null && threads.diff_run !== null && threads.diff_head !== null && (
                    <p className="text-status-blocked" data-testid="head-moved">
                        The PR&apos;s head is <span className="font-mono text-xs">{shortSha(moved)}</span>, past the
                        diff run:{threads.diff_run} kept at{' '}
                        <span className="font-mono text-xs">{shortSha(threads.diff_head)}</span>: a thread may sit on a
                        line that has changed since.
                    </p>
                )}
                {threads.diff === null && (
                    <p className="text-muted-foreground">No run kept a diff of it, so its threads are listed whole.</p>
                )}
            </div>
            <DraftList threads={threads} placed={placed} onFollow={onFollow} />
            {threads.pr_drafts.length > 0 && (
                <div className="flex flex-col gap-2 border-t p-3" data-testid="pr-drafts">
                    <span className="panel-label">The review&apos;s body</span>
                    {threads.pr_drafts.map((d) => (
                        <DraftCard key={`${d.run}-${d.number}`} draft={d} onChange={onChange} />
                    ))}
                </div>
            )}
            {(sendable.length > 0 ||
                held.length > 0 ||
                said !== null ||
                send.error !== null ||
                stage.error !== null) && (
                <PanelFooter>
                    {held.length > 0 && (
                        <p className="text-sm" data-testid="staged-review">
                            {held.length === 1 ? '1 draft waits' : `${held.length} drafts wait`} in the review you
                            staged. Finish and submit it{' '}
                            <a
                                href={`${threads.url}/files`}
                                target="_blank"
                                rel="noreferrer noopener"
                                className="text-accent underline-offset-4 hover:underline"
                            >
                                on GitHub
                            </a>
                            , or delete it there to send them from here; canopy&apos;s next read of the PR settles them.
                        </p>
                    )}
                    {offered && (
                        <span className="flex flex-wrap items-center gap-2">
                            <Button
                                onClick={() => send.mutate()}
                                disabled={busy}
                                title={`canopy draft send ${sendRefs(sendable)}`}
                            >
                                <Send />
                                {send.isPending ? `Sending ${sendable.length}…` : `Send ${sendable.length} waiting`}
                            </Button>
                            <Button
                                variant="outline"
                                onClick={() => stage.mutate()}
                                disabled={busy}
                                title={`canopy draft stage ${sendRefs(sendable)}`}
                            >
                                <GitPullRequestDraft />
                                {stage.isPending ? 'Starting the review…' : 'Start a review on GitHub'}
                            </Button>
                            <span className="text-xs text-muted-foreground">
                                Send posts one comment review, in your name: it approves nothing and resolves no thread.
                                A review started on GitHub holds the same words, for you to add to and submit there
                                {sendable.some((d) => d.reaction !== null) &&
                                    "; its reactions go on their comments now, since GitHub can't keep one pending"}
                                .
                            </span>
                        </span>
                    )}
                    <Notice error={send.error ?? stage.error}>{said}</Notice>
                </PanelFooter>
            )}
        </Panel>
    )
}

/**
 * Every draft for the PR, in the order their cards show, each a row: its status, its run and number, its first line
 * linking to its card, and where the card sits. Following a link to a card on a file opens that file, as a review's
 * findings list does. Nothing when the PR has no draft.
 */
function DraftList({
    threads,
    placed,
    onFollow,
}: {
    threads: PullRequestThreads
    placed: Placed<ReviewThread>
    onFollow: (file: number) => void
}) {
    const listed = listDrafts(threads, placed)
    if (listed.length === 0) {
        return null
    }
    return (
        <div className="border-t" data-testid="draft-list">
            <span className="panel-label block px-3 pt-3">
                Drafts <span className="readout text-muted-foreground">{listed.length}</span>
            </span>
            <ol className="divide-y">
                {listed.map(({ draft, where, file }) => (
                    <ListRow key={draftAnchor(draft)} kind="thread-draft" className="py-2 text-sm">
                        <Chip tone={DRAFT_TONE[draft.status]} word={draft.status} className="justify-center" />
                        <span className="readout text-xs text-muted-foreground">
                            <RunLink id={draft.run} /> {draft.number}
                        </span>
                        {/* A router link, not a bare `#` href, which the page's <base> would send to the root. */}
                        <Link
                            to="/pull-requests/pr"
                            search={{ url: threads.url }}
                            hash={draftAnchor(draft)}
                            onClick={() => {
                                if (file !== null) {
                                    onFollow(file)
                                }
                            }}
                            className={cn(
                                'min-w-0 truncate text-accent underline-offset-4 hover:underline',
                                (draft.status === 'superseded' || draft.status === 'dropped') && 'line-through',
                            )}
                        >
                            <MemoryText text={rowText(draft)} className="whitespace-nowrap" />
                        </Link>
                        <span className="max-w-56 truncate font-mono text-xs text-muted-foreground" title={where}>
                            {where}
                        </span>
                    </ListRow>
                ))}
            </ol>
        </div>
    )
}

// What a draft's row shows: its first line with text, as its card shows the rest, or its reaction when it sends that
// alone, so the row's link is never empty.
function rowText(draft: Pick<Draft, 'text' | 'reaction'>): string {
    const line = draft.text.split('\n').find((l) => l.trim() !== '')
    if (line === undefined && draft.reaction !== null) {
        return `${REACTION_LOOKS[draft.reaction].label}, alone`
    }
    return line ?? draft.text
}

// What `canopy draft send` takes for the drafts, run by run, for the button's hover.
function sendRefs(drafts: Draft[]): string {
    const runs = [...new Set(drafts.map((d) => d.run))]
    return runs
        .map((run) =>
            [`run:${run}`, ...drafts.filter((d) => d.run === run).map((d) => `${d.number}@${d.hash}`)].join(' '),
        )
        .join(' ')
}

/**
 * One review thread: where it is, whether GitHub says it is outdated or resolved, its comments as their authors wrote
 * them, plain text with each `<details>` block folded (`CommentText`), with a link to each on its host, then the
 * feedback plan's proposal for it, `item`, when the plan covers it, then the drafts that answer it. One the operator
 * sent wears `sent by you`. A thread no draft answers shows as it is.
 */
export function ThreadCard({
    thread,
    item,
    onChange,
}: {
    thread: ReviewThread
    item?: FeedbackPlanItem | undefined
    onChange: () => void
}) {
    const where = threadWhere(thread)
    return (
        <article className="rounded-md border bg-surface-raised p-3 text-sm" data-testid="review-thread">
            <header className="flex flex-wrap items-center gap-2">
                {where !== null && <span className="font-mono text-xs break-all text-muted-foreground">{where}</span>}
                {thread.outdated && <Chip>outdated</Chip>}
                {thread.resolved && <Chip>resolved</Chip>}
            </header>
            <ol className="mt-1.5 flex flex-col gap-2">
                {thread.comments.map((c) => (
                    <li key={c.id} className="flex flex-col gap-0.5" data-testid="thread-comment">
                        <span className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                            <span className="font-medium text-foreground">{c.author ?? 'a deleted account'}</span>
                            {c.bot && <Chip>bot</Chip>}
                            {c.operator_sent && <Chip>sent by you</Chip>}
                            {c.created_at !== null && <Age at={c.created_at} variant="ago" />}
                            {c.url !== null && <LinkOut href={c.url} label="The comment on its host" />}
                        </span>
                        <CommentText text={c.body} />
                    </li>
                ))}
            </ol>
            {item !== undefined && <PlanProposal item={item} />}
            {thread.drafts.length > 0 && (
                <div className="mt-2 flex flex-col gap-2">
                    {thread.drafts.map((d) => (
                        <DraftCard key={`${d.run}-${d.number}`} draft={d} onChange={onChange} />
                    ))}
                </div>
            )}
        </article>
    )
}

/**
 * One draft, a worker's text until the operator sends it: its run and number, where it stands, what the run did about
 * its thread, its text, plain, every hidden character named, and the reaction it stages on the comment it answers, if
 * any, which it may send alone. A reaction an earlier send added though the rest of it posted nothing is named, since
 * it is on GitHub already. A waiting draft has Send, Edit, and Drop; one no read
 * has checked yet, Edit and Drop; a dropped one, Undo. Send reads Sending… until the post returns, and a toast says
 * what it did as well as the line under the card. Its hash is the one a send carries, so what posts is the text shown.
 * A draft superseded by this one that carried the operator's edits is named, since they are not carried over. A
 * ticket's draft names the issue it goes to, as the worker read it, for the operator to check. Each verb calls
 * `onChange` once done, to read again what shows the draft.
 */
export function DraftCard({ draft, onChange }: { draft: Draft; onChange: () => void }) {
    const [said, setSaid] = useState<string | null>(null)
    const [editing, setEditing] = useState(false)
    const toast = useToast()
    const send = useMutation({
        mutationFn: () => sendDrafts([draft]),
        onSuccess: (sent) => {
            setSaid(draftsSentText(sent))
            toast(draftsSentToast(sent))
            onChange()
        },
    })
    const drop = useMutation({
        mutationFn: (undo: boolean) => dropDraft(draft.run, draft.number, undo),
        onSuccess: (dropped) => {
            setSaid(draftDroppedText(dropped))
            onChange()
        },
    })
    const busy = send.isPending || drop.isPending
    const ref = `run:${draft.run} ${draft.number}`
    // Only a review comment takes a reaction.
    const reacts = draft.kind === 'thread'
    return (
        <DraftCardFrame
            id={draftAnchor(draft)}
            waiting={draft.status === 'waiting'}
            testId="draft"
            status={draft.status}
            header={
                <>
                    <span className="panel-label">Draft</span>
                    <span className="readout text-xs text-muted-foreground">
                        <RunLink id={draft.run} /> {draft.number}
                    </span>
                    <Chip tone={DRAFT_TONE[draft.status]} word={draft.status} />
                    {draft.stance !== null && <Word word={draft.stance} className="text-xs text-muted-foreground" />}
                    {draft.edited && <Chip>your text</Chip>}
                    <span className="ml-auto font-mono text-2xs text-muted-foreground" title="The hash a send carries">
                        {draft.hash}
                    </span>
                </>
            }
        >
            {draft.why !== null && draft.status !== 'waiting' && (
                <p className="mt-1 text-xs text-muted-foreground">{draft.why}</p>
            )}
            {draft.supersedes_edited && open(draft) && (
                <p className="mt-1 text-xs text-status-blocked" data-testid="supersedes-edited">
                    It replaces a draft you edited, and your edits are not carried over: read it before you send it.
                </p>
            )}
            {draft.issue_url !== null && (
                <p className="mt-1 text-xs text-muted-foreground" data-testid="draft-issue">
                    To <span className="font-mono break-all text-foreground">{draft.issue_url}</span>, as the worker
                    named it
                </p>
            )}
            {editing ? (
                <EditDraft
                    draft={draft}
                    onSaved={(text) => {
                        setSaid(text)
                        setEditing(false)
                        onChange()
                    }}
                    onCancel={() => setEditing(false)}
                />
            ) : (
                <>
                    {draft.text !== '' && (
                        <MemoryText
                            text={draft.text}
                            lines
                            className={cn(
                                'mt-1.5 block',
                                (draft.status === 'superseded' || draft.status === 'dropped') &&
                                    'text-muted-foreground line-through',
                            )}
                        />
                    )}
                    {draft.reaction !== null && <StagedReaction reaction={draft.reaction} alone={draft.text === ''} />}
                </>
            )}
            {draft.reacted !== null && draft.status !== 'sent' && (
                <p className="mt-1 text-xs text-status-blocked" data-testid="draft-reacted">
                    {REACTION_LOOKS[draft.reacted].label} is on the comment already: a send that posted nothing else
                    added it, and sending again adds no second.
                </p>
            )}
            {!editing &&
                (open(draft) || draft.status === 'dropped' || draft.status === 'staged' || draft.sent_url !== null) && (
                    <DraftVerbs>
                        {draft.status === 'waiting' && (
                            <Button
                                size="sm"
                                onClick={() => send.mutate()}
                                disabled={busy}
                                title={`canopy draft send run:${draft.run} ${draft.number}@${draft.hash}`}
                            >
                                <Send />
                                {send.isPending ? 'Sending…' : 'Send'}
                            </Button>
                        )}
                        {open(draft) && (
                            <>
                                <EditVerb
                                    onClick={() => setEditing(true)}
                                    disabled={busy}
                                    title={`canopy draft edit ${ref} --text TEXT${reacts ? ' --react NAME' : ''}`}
                                />
                                <DropVerb
                                    onClick={() => drop.mutate(false)}
                                    disabled={busy}
                                    title={`canopy draft drop ${ref}`}
                                />
                            </>
                        )}
                        {draft.status === 'dropped' && (
                            <Button
                                size="sm"
                                variant="ghost"
                                onClick={() => drop.mutate(true)}
                                disabled={busy}
                                title={`canopy draft drop ${ref} --undo`}
                            >
                                <Undo2 />
                                Undo
                            </Button>
                        )}
                        {draft.sent_url !== null && <LinkOut href={draft.sent_url} label="The reply on its host" />}
                        {draft.status === 'unchecked' && (
                            <span className="text-xs text-muted-foreground">
                                It is sent once canopy has read its thread.
                            </span>
                        )}
                        {draft.status === 'staged' && (
                            <span className="text-xs text-muted-foreground">
                                It is in the review you staged, for you to submit on GitHub.
                            </span>
                        )}
                    </DraftVerbs>
                )}
            <Notice error={send.error ?? drop.error} className="mt-1.5">
                {said}
            </Notice>
        </DraftCardFrame>
    )
}

/** The reaction a draft stages on the comment it answers, alone when it sends no reply. */
function StagedReaction({ reaction, alone }: { reaction: Reaction; alone: boolean }) {
    const look = REACTION_LOOKS[reaction]
    return (
        <p className="mt-1.5 flex items-center gap-1.5 text-xs text-muted-foreground" data-testid="draft-reaction">
            <span aria-hidden="true" className="text-sm">
                {look.emoji}
            </span>
            {alone
                ? `${look.label} on the comment it answers, alone: no reply.`
                : `${look.label} on the comment it answers, with the reply.`}
        </p>
    )
}

/**
 * A draft's words in the operator's own, as `canopy draft edit`: plain text, held to the bound a draft is, and for a
 * thread's draft the reaction it stages, picked from the ones GitHub offers or none, so the text may be empty to send
 * the reaction alone: once one is picked, Clear text empties it in a click. Kept as a new version beside the run's own.
 */
function EditDraft({
    draft,
    onSaved,
    onCancel,
}: {
    draft: Draft
    onSaved: (said: string) => void
    onCancel: () => void
}) {
    const id = useId()
    const [text, setText] = useState(draft.text)
    const [reaction, setReaction] = useState(draft.reaction)
    return (
        <DraftForm
            label={`Edit run:${draft.run}'s draft ${draft.number}`}
            text={text}
            onText={setText}
            fits={text.trim() !== '' || (reaction !== null && text === '')}
            save={() => editDraft(draft.run, draft.number, text, reaction)}
            onSaved={(edited) => onSaved(draftEditedText(edited))}
            onCancel={onCancel}
        >
            {draft.kind === 'thread' && (
                <span className="flex flex-wrap items-center gap-2">
                    <span className="panel-label" id={`${id}-reaction`}>
                        Reaction
                    </span>
                    <ToggleGroup
                        type="single"
                        value={reaction ?? ''}
                        onValueChange={(value) => setReaction(reactionOf(value))}
                        aria-labelledby={`${id}-reaction`}
                    >
                        {REACTIONS.map((r) => (
                            <ToggleGroupItem key={r} value={r} aria-label={REACTION_LOOKS[r].label} title={r}>
                                <span aria-hidden="true" className="text-sm">
                                    {REACTION_LOOKS[r].emoji}
                                </span>
                            </ToggleGroupItem>
                        ))}
                    </ToggleGroup>
                    {reaction !== null && text !== '' ? (
                        <Button
                            type="button"
                            size="sm"
                            variant="ghost"
                            onClick={() => setText('')}
                            title="Empty the text, to send the reaction alone"
                        >
                            <Eraser />
                            Clear text
                        </Button>
                    ) : (
                        <span className="text-xs text-muted-foreground">
                            {reaction === null ? 'None.' : 'Sent alone, with no reply.'}
                        </span>
                    )}
                </span>
            )}
        </DraftForm>
    )
}
