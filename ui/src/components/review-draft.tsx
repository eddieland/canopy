import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { GitPullRequestDraft, Pencil, Send, Trash2, WandSparkles } from 'lucide-react'
import { useEffect, useId, useRef, useState } from 'react'
import type { KeyboardEvent as ReactKeyboardEvent, SubmitEvent } from 'react'

import {
    addReviewDraftComment,
    discardReviewDraft,
    dropReviewDraftComment,
    editReviewDraftBody,
    editReviewDraftComment,
    noteReviewDraft,
    publishReviewDraft,
    showReviewDraft,
} from '@/api/mutations'
import type { ReviewDraft, ReviewDraftComment, ReviewSummary } from '@/api/types'
import { useDismissReviewFinding } from '@/components/dismiss-finding'
import type { DismissalWords } from '@/components/dismiss-finding'
import { DraftCardFrame, DraftForm, DraftVerbs, DropVerb, EditVerb } from '@/components/draft-card'
import { Textarea } from '@/components/input'
import { Leaf } from '@/components/leaf'
import { MemoryText } from '@/components/memory-text'
import { Notice } from '@/components/notice'
import { Panel, PanelFooter, PanelHeader } from '@/components/panel'
import { ReviewLink } from '@/components/review-link'
import { RichText } from '@/components/rich-text'
import { ListRow } from '@/components/rows'
import { SendKeycap } from '@/components/send-keycap'
import { Chip } from '@/components/status'
import { Tip } from '@/components/tip'
import { Button } from '@/components/ui/button'
import { useToast } from '@/hooks/use-toast'
import { reviewDraftDescription } from '@/lib/descriptions'
import {
    reviewDraftDiscardedToast,
    reviewDraftEditedText,
    reviewDraftNotedText,
    reviewDraftPublishedText,
    reviewDraftPublishedToast,
    reviewPointText,
} from '@/lib/outcomes'
import {
    MAX_NOTE_CHARS,
    REVIEW_DRAFT_TONE,
    commentAnchor,
    editable,
    leftOut,
    pointState,
    revisionStanding,
    versionBy,
} from '@/lib/review-drafts'
import type { Adding, PointState } from '@/lib/review-drafts'
import { findingAnchor, SEVERITY_TONE, shortSha } from '@/lib/reviews'
import type { Numbered } from '@/lib/reviews'
import { useSendKeys } from '@/lib/send-key'
import { cn } from '@/lib/utils'

// What the draft is, around the commit the review read.
const INTRO = [
    'What canopy would post on the PR in your name, word for word and unmarked: one comment review on ',
    " that approves nothing. The reviewer wrote it from the PR's text, so read it before you publish it.",
] as const

// The end of the line by the publish buttons: what the review is not, and what the other button does.
const POSTS_STAGED =
    ': it approves nothing. A review started on GitHub holds the same, seen by you alone until you submit it there.'

// A finding's card's one control, while the draft waits: leaving it out of the review is dismissing it, which drops
// its comment or its part of the body, and putting it back is taking that back, which restores the reviewer's words.
const POINT_WORDS: DismissalWords = {
    labels: ['leave out', 'put back'],
    titles: [
        'Dismiss it: its comment leaves your review',
        "Take the dismissal back: it returns in the reviewer's words",
    ],
    said: reviewPointText,
}

// The same control on a finding left out by a drop, not a dismissal: the server puts a finding back only by taking a
// dismissal back, so it is dismissed first.
const DROPPED_WORDS: DismissalWords = {
    ...POINT_WORDS,
    labels: ['dismiss', 'put back'],
    titles: ['Dismiss it, so that put back can restore its comment', POINT_WORDS.titles[1]],
}

// What each place a finding may stand in the draft is called on its card.
const POINT_CHIP: Record<PointState['kind'], string> = {
    comment: 'in your review',
    body: 'in your review',
    out: 'left out',
}

/**
 * A draft's state, for the description of the review's page it leads: its status's chip in its tone, then its version
 * and what the status means for the operator (`reviewDraftDescription`).
 */
export function ReviewDraftState({ draft }: { draft: ReviewDraft }) {
    return (
        <span className="inline-flex flex-wrap items-center gap-x-2" data-testid="draft-state">
            <Chip tone={REVIEW_DRAFT_TONE[draft.status]} word={draft.status} />
            {reviewDraftDescription(draft)}
        </span>
    )
}

// A review that answers no request in several personas: one array, as a default made in the signature would be a
// new one on every render.
const NO_SIBLINGS: ReviewSummary[] = []

/**
 * A review of a PR the loop does not own as the comment review canopy would post in the operator's name (DESIGN §34):
 * its newest version word for word, the body here and each comment on its line of the diff, every hidden character
 * named, since the reviewer wrote it from the PR's text. While it waits, the body is edited here, each comment on its
 * card, and a comment added on any line of the diff; each change is a new version, as `canopy review edit` makes.
 * Publishing posts the version shown, named by its hash, as one comment review on the commit the review read:
 * submitted now, as `--submit` does, or left pending on GitHub for the operator to submit there. A staged one says
 * where to finish it, a published one links to it. With no diff kept, its comments are listed here. It leads the
 * review's page, whose description says its status (`ReviewDraftState`), so its header names only its version, with
 * what made it and its hash on hover. `findings` is how many the review reported, so the list can say which the draft
 * leaves out. A note asks the next tick for a revision by an agent, as `canopy reply review:ID` does, and the
 * panel says while one is asked for or running; the version it makes is listed with the rest. `onFollow` hears a
 * link followed to a comment's card, by its file's index in the diff. `siblings` are the reviews its request made of
 * the same commit in its other personas, named under the intro so the operator picks one.
 */
export function ReviewDraftPanel({
    run,
    prUrl,
    sha,
    draft,
    findings,
    hasDiff,
    onFollow,
    siblings = NO_SIBLINGS,
}: {
    run: number
    prUrl: string
    sha: string
    draft: ReviewDraft
    findings: number
    hasDiff: boolean
    onFollow: (file: number) => void
    siblings?: ReviewSummary[]
}) {
    const client = useQueryClient()
    const [editingBody, setEditingBody] = useState(false)
    const [said, setSaid] = useState<string | null>(null)
    const open = editable(draft)
    return (
        <Panel data-testid="review-draft">
            <PanelHeader label="Draft review">
                {/* Its status is the page's description; what made the version, and its hash, are on hover. */}
                <Tip
                    fact={
                        `Version ${draft.version}: ${draft.change}, ${versionBy(draft)}. ` +
                        `A publish carries its hash, ${draft.hash}.`
                    }
                >
                    <span className="readout text-xs text-muted-foreground" data-testid="draft-version">
                        version {draft.version}
                    </span>
                </Tip>
            </PanelHeader>
            <div className="flex flex-col gap-2 p-3 text-sm">
                <p className="text-muted-foreground">
                    {INTRO[0]}
                    <span className="font-mono text-xs">{shortSha(sha)}</span>
                    {INTRO[1]}
                </p>
                {draft.moved_head !== null && (
                    <p className="text-status-blocked" data-testid="draft-head-moved">
                        {"The PR's head is "}
                        <span className="font-mono text-xs">{shortSha(draft.moved_head)}</span>
                        {' now: its comments would show as outdated, on the commit the review read.'}
                    </p>
                )}
                {siblings.length > 0 && <Siblings siblings={siblings} />}
                {draft.why !== null && <p className="text-xs text-muted-foreground">{draft.why}</p>}
                {draft.refused.map((why) => (
                    <p key={why} className="text-xs text-status-failed">
                        Left out: {why}
                    </p>
                ))}
            </div>
            <div className="flex flex-col gap-1.5 border-t p-3 text-sm" data-testid="draft-body">
                <span className="flex items-center gap-2">
                    <span className="panel-label">Body</span>
                    {open && !editingBody && (
                        <Button
                            size="xs"
                            variant="ghost"
                            className="-my-1 text-muted-foreground"
                            onClick={() => setEditingBody(true)}
                            title={`canopy review edit ${run} --body --text TEXT`}
                        >
                            <Pencil />
                            edit
                        </Button>
                    )}
                </span>
                {editingBody ? (
                    <DraftTextForm
                        label={`Edit review run ${run}'s draft's body`}
                        initial={draft.body}
                        allowEmpty
                        save={(text) => editReviewDraftBody(run, text)}
                        onSaved={(saved) => {
                            setSaid(reviewDraftEditedText(run, saved))
                            setEditingBody(false)
                            void showReviewDraft(client, run, saved)
                        }}
                        onCancel={() => setEditingBody(false)}
                    />
                ) : draft.body === '' ? (
                    <p className="text-muted-foreground">No body: the comments post alone.</p>
                ) : (
                    <MemoryText text={draft.body} lines className="block" />
                )}
            </div>
            <CommentList run={run} draft={draft} findings={findings} hasDiff={hasDiff} onFollow={onFollow} />
            <VersionList draft={draft} />
            {(editable(draft) || draft.revisions.length > 0) && <RevisionSection run={run} draft={draft} />}
            <PublishFooter run={run} prUrl={prUrl} sha={sha} draft={draft} said={said} onSaid={setSaid} />
        </Panel>
    )
}

/**
 * The reviews the same request made of the same commit in its other personas, each named by its persona and opening
 * its page: each holds a draft of its own, so the operator reads them side by side and publishes the one they want.
 * Publishing one leaves the others as they are.
 */
function Siblings({ siblings }: { siblings: ReviewSummary[] }) {
    return (
        <p className="text-muted-foreground" data-testid="draft-siblings">
            Also reviewed as{' '}
            {siblings.map((r, i) => (
                <span key={r.id}>
                    {i > 0 && ', '}
                    <ReviewLink id={r.id}>{r.persona}</ReviewLink>
                </span>
            ))}
            {', from the same request at this commit. Each is a draft of its own: publish the one you want, and ' +
                'the others stay as they are.'}
        </p>
    )
}

/**
 * The draft's comments, one row per point of the review that posts as one, each linking to its card on the diff: a
 * finding's card, which is its comment's too, or the operator's own comment's. With no diff kept, the rows are the
 * comments' cards themselves. Lines under them say which findings the draft leaves out, and how to add a comment.
 */
function CommentList({
    run,
    draft,
    findings,
    hasDiff,
    onFollow,
}: {
    run: number
    draft: ReviewDraft
    findings: number
    hasDiff: boolean
    onFollow: (file: number) => void
}) {
    const count = draft.comments.length
    const out = hasDiff ? leftOut(draft, findings) : []
    return (
        <div className="border-t" data-testid="draft-comments">
            <span className="panel-label block px-3 pt-3">
                Comments{' '}
                <span className="readout text-muted-foreground">
                    {count} of at most {draft.max_comments}
                </span>
            </span>
            {hasDiff ? (
                <ol className="divide-y">
                    {draft.comments.map((c) => (
                        <ListRow key={c.number} kind="draft-comment" className="py-2 text-sm">
                            <span className="readout text-xs text-muted-foreground">{c.number}</span>
                            <Chip className="justify-center">
                                {c.finding === null ? 'yours' : `finding ${c.finding}`}
                            </Chip>
                            {/* A router link, not a bare `#` href, which the page's <base> would send to the root. */}
                            <Link
                                to="/pull-requests/reviews/$id"
                                params={{ id: String(run) }}
                                hash={c.finding === null ? commentAnchor(c.number) : findingAnchor(c.finding)}
                                onClick={() => {
                                    if (c.file !== null) {
                                        onFollow(c.file)
                                    }
                                }}
                                className="min-w-0 truncate text-accent underline-offset-4 hover:underline"
                            >
                                <MemoryText text={firstLine(c.text)} className="whitespace-nowrap" />
                            </Link>
                            <span className="max-w-56 truncate font-mono text-xs text-muted-foreground">
                                {c.path}:{c.line}
                            </span>
                        </ListRow>
                    ))}
                </ol>
            ) : (
                <div className="flex flex-col gap-2 p-3">
                    {draft.comments.map((c) => (
                        <DraftCommentCard key={c.number} run={run} comment={c} draft={draft} />
                    ))}
                </div>
            )}
            {out.length > 0 && (
                <p className="px-3 pb-3 text-xs text-muted-foreground" data-testid="draft-left-out">
                    {leftOutText(out)}
                    {editable(draft) && ' Put one back on its card.'}
                </p>
            )}
            {editable(draft) && hasDiff && (
                <p className="px-3 pb-3 text-xs text-muted-foreground">
                    Add one with the + beside a line&apos;s number on the diff below.
                </p>
            )}
            {count === 0 && !(editable(draft) && hasDiff) && (
                <p className="px-3 pb-3 text-xs text-muted-foreground">None: the body posts alone.</p>
            )}
        </div>
    )
}

// Which findings the draft leaves out, as a sentence.
function leftOutText(out: readonly number[]): string {
    const last = out.at(-1)
    if (out.length === 1) {
        return `Left out: finding ${last}.`
    }
    return `Left out: findings ${out.slice(0, -1).join(', ')} and ${last}.`
}

// A comment's first line with text, for its row, so the row's link is never empty.
function firstLine(text: string): string {
    return text.split('\n').find((l) => l.trim() !== '') ?? text
}

/** Every version of the draft, oldest first: its number, hash, who wrote it, and what it changed. */
function VersionList({ draft }: { draft: ReviewDraft }) {
    return (
        <div className="border-t p-3" data-testid="draft-versions">
            <span className="panel-label">Versions</span>
            <ol className="mt-1 flex flex-col gap-0.5 font-mono text-xs text-muted-foreground">
                {draft.versions.map((v) => (
                    <li key={v.number} className={cn(v.number === draft.version && 'text-foreground')}>
                        {v.number} {v.hash} {versionBy(v)}: {v.change}
                    </li>
                ))}
            </ol>
        </div>
    )
}

/**
Revising the draft with an agent (DESIGN §34): the operator's notes no version has answered, its revisions against
 * their limit, and, while it waits, the form of a note, as `canopy reply review:RUN TEXT`. A note asks the
 * next tick for a revision, which reads the PR and the version shown and makes a new one, posting nothing; a version
 * the operator makes first answers it instead.
 */
function RevisionSection({ run, draft }: { run: number; draft: ReviewDraft }) {
    const client = useQueryClient()
    const id = useId()
    const sendKeys = useSendKeys()
    const [text, setText] = useState('')
    const [said, setSaid] = useState<string | null>(null)
    const note = useMutation({
        mutationFn: () => noteReviewDraft(run, text),
        onSuccess: (noted) => {
            setSaid(reviewDraftNotedText(run, noted))
            setText('')
            void showReviewDraft(client, run, noted.draft)
        },
    })
    const latest = draft.revisions[0]
    const chars = text.trim().length
    const fits = chars > 0 && chars <= MAX_NOTE_CHARS

    function submit(event: SubmitEvent<HTMLFormElement>) {
        event.preventDefault()
        if (fits && !note.isPending) {
            note.mutate()
        }
    }

    return (
        <div className="flex flex-col gap-2 border-t p-3 text-sm" data-testid="draft-revision">
            <span className="flex items-baseline gap-2">
                <span className="panel-label">Revision</span>
                <span className="readout text-xs text-muted-foreground">
                    {draft.revisions.length} of {draft.revision_limit} revisions
                </span>
            </span>
            {editable(draft) && <p className="text-muted-foreground">{standingText(run, draft)}</p>}
            {latest?.state === 'failed' && (
                <p className="text-xs text-status-failed">
                    Revision run {latest.id} ended {latest.status}: the draft stands as it was.
                </p>
            )}
            {draft.notes.length > 0 && (
                <ol className="flex flex-col gap-1.5" aria-label="Your notes">
                    {draft.notes.map((n) => (
                        <li key={n.id} className="rounded-md border bg-surface px-2.5 py-1.5">
                            <span className="readout block text-2xs text-muted-foreground">
                                note {n.id}, at version {n.after_version}, through {n.channel}
                            </span>
                            <MemoryText text={n.body} lines className="block" />
                        </li>
                    ))}
                </ol>
            )}
            {draft.revisions.length > 0 && (
                <ol className="flex flex-col gap-0.5 font-mono text-xs text-muted-foreground" aria-label="Revisions">
                    {draft.revisions.map((r) => (
                        <li key={r.id}>
                            review run {r.id}, of version {r.revised}: {r.status}
                        </li>
                    ))}
                </ol>
            )}
            {editable(draft) && (
                <form onSubmit={submit} aria-label={`Ask for a revision of review run ${run}'s draft`}>
                    <span className="flex items-baseline justify-between gap-3">
                        <label className="panel-label" htmlFor={`${id}-note`}>
                            What should change
                        </label>
                        <span
                            className={cn(
                                'readout text-xs text-muted-foreground',
                                chars > MAX_NOTE_CHARS && 'text-status-failed',
                            )}
                        >
                            {chars} of {MAX_NOTE_CHARS}
                        </span>
                    </span>
                    <Textarea
                        id={`${id}-note`}
                        value={text}
                        onChange={(event) => setText(event.target.value)}
                        onKeyDown={sendKeys.onKeyDown}
                        spellCheck
                        placeholder="Fold the nits into one comment, and say the retry finding more gently"
                        className="mt-1.5 min-h-16"
                    />
                    <Button
                        type="submit"
                        size="sm"
                        variant="outline"
                        className="mt-2"
                        disabled={note.isPending || !fits}
                        title={`canopy reply review:${run} TEXT`}
                        aria-keyshortcuts={sendKeys.shortcut}
                    >
                        <WandSparkles />
                        {note.isPending ? 'Asking…' : 'Ask for a revision'}
                        <SendKeycap keys={sendKeys.shortcut} />
                    </Button>
                </form>
            )}
            <Notice error={note.error}>{said}</Notice>
        </div>
    )
}

// What the section says of a waiting draft's revisions, in the CLI's words where `canopy review draft` has them.
function standingText(run: number, draft: ReviewDraft): string {
    const standing = revisionStanding(draft)
    switch (standing.kind) {
        case 'running': {
            return `Review run ${standing.run} is revising it on your notes. A note or a publish waits for it to end.`
        }
        case 'spent': {
            const grant =
                `It has had its ${draft.revision_limit} revisions: allow it another with ` +
                `\`canopy grant review:${run} revision\`.`
            return standing.asked ? `${grant} Your note waits for that.` : grant
        }
        case 'asked': {
            return 'Your note asks for a revision: the next tick starts one, unless you change the draft first.'
        }
        case 'open': {
            return (
                'Tell an agent what to change, and the next tick revises the draft: it reads the PR and this version ' +
                'and makes a new one. It posts nothing.'
            )
        }
    }
}

/**
 * Publishing the version shown, as `canopy review publish RUN HASH`, as a PR's thread drafts are sent: `Publish
 * version N` submits it now (`--submit`), and an outline `Start the review on GitHub` beside it stages it, a pending
 * review for the operator to submit there. A line beside them says what posts, as whom, on whose PR, and on which
 * commit. A toast says what a publish did; a draft staged or published says so in one linked line, and one of unknown
 * outcome or not published says why. A publish that posted the review, and only that, drops a leaf off the footer, as
 * approving a plan does: the review is done with, and nothing else waits on it here. A ghost `Discard`, as `canopy
 * review discard RUN`, asks in its place whether to post nothing, and a discarded draft says so in one line.
 */
function PublishFooter({
    run,
    prUrl,
    sha,
    draft,
    said,
    onSaid,
}: {
    run: number
    prUrl: string
    sha: string
    draft: ReviewDraft
    said: string | null
    onSaid: (said: string | null) => void
}) {
    const client = useQueryClient()
    const toast = useToast()
    // How many publishes here posted the review, not staged it: each drops its leaf once.
    const [posted, setPosted] = useState(0)
    const publish = useMutation({
        mutationFn: (submit: boolean) => publishReviewDraft(run, draft.hash, submit),
        onSuccess: (published) => {
            onSaid(reviewDraftPublishedText(run, published))
            toast(reviewDraftPublishedToast(run, prUrl, published))
            if (published.draft.status === 'published') {
                setPosted((n) => n + 1)
            }
            void showReviewDraft(client, run, published.draft)
        },
    })
    const [discarding, setDiscarding] = useState(false)
    const discard = useMutation({
        mutationFn: () => discardReviewDraft(run),
        onSuccess: (saved) => {
            setDiscarding(false)
            toast(reviewDraftDiscardedToast(run, prUrl))
            void showReviewDraft(client, run, saved)
        },
    })
    const empty = draft.body === '' && draft.comments.length === 0
    // Which of the two is on its way, so only that one says so.
    const submitting = publish.isPending ? publish.variables : null
    return (
        <PanelFooter className="relative">
            {/* Placed from the footer's corner, over room the buttons leave once published, so it takes none. */}
            {posted > 0 && <Leaf key={posted} className="top-1 right-3" />}
            {editable(draft) && discarding && (
                <ConfirmDiscard
                    pending={discard.isPending}
                    onConfirm={() => discard.mutate()}
                    onKeep={() => setDiscarding(false)}
                />
            )}
            {editable(draft) && !discarding && (
                <span className="flex flex-wrap items-center gap-2">
                    <Button
                        onClick={() => publish.mutate(true)}
                        disabled={publish.isPending || empty}
                        title={`canopy review publish ${run} ${draft.hash} --submit`}
                    >
                        <Send />
                        {submitting === true ? 'Publishing…' : `Publish version ${draft.version}`}
                    </Button>
                    <Button
                        variant="outline"
                        onClick={() => publish.mutate(false)}
                        disabled={publish.isPending || empty}
                        title={`canopy review publish ${run} ${draft.hash}`}
                    >
                        <GitPullRequestDraft />
                        {submitting === false ? 'Starting the review…' : 'Start the review on GitHub'}
                    </Button>
                    <Button
                        variant="ghost"
                        onClick={() => setDiscarding(true)}
                        disabled={publish.isPending}
                        title={`canopy review discard ${run}`}
                    >
                        <Trash2 />
                        Discard
                    </Button>
                    <span className="text-xs text-muted-foreground" data-testid="draft-posts">
                        {empty ? (
                            'Nothing to post yet: it needs a body or a comment.'
                        ) : (
                            <>
                                {`Publish posts ${postsWhat(draft)} as your comment review, unmarked, on `}
                                {draft.pr_author === null ? 'the PR' : `${draft.pr_author}'s PR`}
                                {', at '}
                                <span className="font-mono">{shortSha(sha)}</span>
                                {POSTS_STAGED}
                            </>
                        )}
                    </span>
                </span>
            )}
            {draft.status === 'staged' && (
                <p className="text-sm" data-testid="draft-staged">
                    Version {draft.version} waits in the review you staged. Submit or delete it{' '}
                    <a
                        href={`${prUrl}/files`}
                        target="_blank"
                        rel="noreferrer noopener"
                        className="text-accent underline-offset-4 hover:underline"
                    >
                        on GitHub
                    </a>
                    ; canopy&apos;s next read of the PR settles it.
                </p>
            )}
            {draft.status === 'published' && draft.published_url !== null && (
                <p className="text-sm" data-testid="draft-published">
                    Published version {draft.version} as your review{' '}
                    <a
                        href={draft.published_url}
                        target="_blank"
                        rel="noreferrer noopener"
                        className="text-accent underline-offset-4 hover:underline"
                    >
                        on GitHub
                    </a>
                    . A later commit&apos;s review is a draft of its own.
                </p>
            )}
            {draft.status === 'discarded' && (
                <p className="text-sm" data-testid="draft-discarded">
                    You discarded this draft, so nothing was posted. A later commit&apos;s review is a draft of its own.
                </p>
            )}
            <Notice error={publish.error ?? discard.error}>{said}</Notice>
        </PanelFooter>
    )
}

// Discarding asked about in its place in the foot, as skipping a plan is: nothing on this page undoes it. Keep, the
// choice that loses nothing, takes the focus, and Escape keeps too.
function ConfirmDiscard({
    pending,
    onConfirm,
    onKeep,
}: {
    pending: boolean
    onConfirm: () => void
    onKeep: () => void
}) {
    const keep = useRef<HTMLButtonElement>(null)
    useEffect(() => {
        keep.current?.focus()
    }, [])
    function onKey(event: ReactKeyboardEvent<HTMLButtonElement>) {
        if (event.key === 'Escape') {
            event.preventDefault()
            onKeep()
        }
    }
    return (
        <fieldset className="flex flex-wrap items-center gap-2">
            <legend className="float-left mr-1 text-sm">
                Discard the draft? Nothing posts, and it takes no edit after.
            </legend>
            <Button ref={keep} type="button" variant="ghost" onClick={onKeep} onKeyDown={onKey}>
                Keep
            </Button>
            <Button type="button" variant="outline" onClick={onConfirm} onKeyDown={onKey} disabled={pending}>
                <Trash2 />
                {pending ? 'Discarding…' : 'Discard the draft'}
            </Button>
        </fieldset>
    )
}

// What a publish would post of the draft: its body, its comments, or both.
function postsWhat(draft: ReviewDraft): string {
    const n = draft.comments.length
    const comments = n === 1 ? '1 comment' : `${n} comments`
    if (draft.body === '') {
        return `${comments}, no body,`
    }
    return n === 0 ? 'the body alone' : `the body and ${comments}`
}

/**
 * One comment of the draft as a card of its own: one the operator added, at its line of the diff, or, with no diff
 * kept, any, in the draft's list. On the diff, a comment made from a finding is that finding's card instead
 * (`ReviewPointCard`). It shows its number, the finding it was made from or that it is the operator's, and its text,
 * plain, every hidden character named. While the draft waits, Edit puts its text in a form and Drop leaves it out,
 * each a new version; dropping one made from a finding leaves the finding as it is.
 */
export function DraftCommentCard({
    run,
    comment,
    draft,
}: {
    run: number
    comment: ReviewDraftComment
    draft: ReviewDraft
}) {
    const client = useQueryClient()
    const [editing, setEditing] = useState(false)
    const [said, setSaid] = useState<string | null>(null)
    const drop = useMutation({
        mutationFn: () => dropReviewDraftComment(run, comment.number),
        onSuccess: (saved) => void showReviewDraft(client, run, saved),
    })
    const open = editable(draft)
    return (
        <DraftCardFrame
            id={commentAnchor(comment.number)}
            waiting={open}
            testId="draft-comment"
            header={
                <>
                    <span className="panel-label">Comment {comment.number}</span>
                    <Chip>{comment.finding === null ? 'yours' : `from finding ${comment.finding}`}</Chip>
                    <span className="font-mono text-xs break-all text-muted-foreground">
                        {comment.path}:{comment.line}
                    </span>
                </>
            }
        >
            {editing ? (
                <DraftTextForm
                    label={`Edit comment ${comment.number} of review run ${run}'s draft`}
                    initial={comment.text}
                    save={(text) => editReviewDraftComment(run, comment.number, text)}
                    onSaved={(saved) => {
                        setSaid(reviewDraftEditedText(run, saved))
                        setEditing(false)
                        void showReviewDraft(client, run, saved)
                    }}
                    onCancel={() => setEditing(false)}
                />
            ) : (
                <MemoryText text={comment.text} lines className="mt-1.5 block" />
            )}
            {open && !editing && (
                <DraftVerbs>
                    <EditVerb
                        onClick={() => setEditing(true)}
                        disabled={drop.isPending}
                        title={`canopy review edit ${run} --comment ${comment.number} --text TEXT`}
                    />
                    <DropVerb
                        onClick={() => drop.mutate()}
                        disabled={drop.isPending}
                        title={`canopy review edit ${run} --drop ${comment.number}`}
                    />
                </DraftVerbs>
            )}
            <Notice error={drop.error} className="mt-1.5">
                {said}
            </Notice>
        </DraftCardFrame>
    )
}

/**
 * One finding of a review with a draft, on the diff, as one card with what the draft makes of it (DESIGN §34): one
 * point of the operator's review, never a finding's card beside a comment's. Its head line is the finding's number,
 * severity, title, and where, then whether it is in the review or left out. In it as a comment, its text is that
 * comment as it will post, every hidden character named, and Edit changes it in place, as `canopy review edit
 * --comment` does; in it through the body, or left out, its text is the reviewer's detail. One control at the end of
 * its head line leaves it out or puts it back, by dismissing the finding or taking that back (`POINT_WORDS`). Once
 * the draft is published or on its way, the control is the plain dismissal again, which changes the draft no more.
 */
export function ReviewPointCard({ run, numbered, draft }: { run: number; numbered: Numbered; draft: ReviewDraft }) {
    const client = useQueryClient()
    const { n, finding } = numbered
    const point = pointState(draft, n)
    const open = editable(draft)
    const dropped = point.kind === 'out' && !finding.dismissed
    const words = open ? (dropped ? DROPPED_WORDS : POINT_WORDS) : undefined
    const { button, notice } = useDismissReviewFinding(run, n, finding.dismissed, words)
    const [editing, setEditing] = useState(false)
    const [said, setSaid] = useState<string | null>(null)
    const out = point.kind === 'out'
    return (
        <DraftCardFrame
            id={findingAnchor(n)}
            waiting={open && !out}
            testId="review-point"
            status={point.kind}
            header={
                <>
                    <span className="readout text-xs text-muted-foreground">{n}</span>
                    <Chip tone={SEVERITY_TONE[finding.severity]}>{finding.severity}</Chip>
                    <span className={cn('font-medium', out && 'text-muted-foreground')}>{finding.title}</span>
                    {finding.location && (
                        <span className="font-mono text-xs break-all text-muted-foreground">{finding.location}</span>
                    )}
                    <Chip>{POINT_CHIP[point.kind]}</Chip>
                    <span className="ml-auto">{button}</span>
                </>
            }
        >
            {point.kind === 'comment' &&
                (editing ? (
                    <DraftTextForm
                        label={`Edit comment ${point.comment.number} of review run ${run}'s draft`}
                        initial={point.comment.text}
                        save={(text) => editReviewDraftComment(run, point.comment.number, text)}
                        onSaved={(saved) => {
                            setSaid(reviewDraftEditedText(run, saved))
                            setEditing(false)
                            void showReviewDraft(client, run, saved)
                        }}
                        onCancel={() => setEditing(false)}
                    />
                ) : (
                    <MemoryText text={point.comment.text} lines className="mt-1.5 block" />
                ))}
            {point.kind !== 'comment' && finding.detail && (
                <RichText text={finding.detail} className="mt-1.5 text-muted-foreground" />
            )}
            {point.kind === 'body' && (
                <p className="mt-1.5 text-xs text-muted-foreground">
                    No line of the diff takes it, so it posts in the body, under its location: edit it there.
                </p>
            )}
            {open && dropped && (
                <p className="mt-1.5 text-xs text-muted-foreground">
                    Its comment was dropped from your review. To have it back, dismiss the finding, then put it back.
                </p>
            )}
            {open && point.kind === 'comment' && !editing && (
                <DraftVerbs>
                    <EditVerb
                        onClick={() => setEditing(true)}
                        disabled={false}
                        title={`canopy review edit ${run} --comment ${point.comment.number} --text TEXT`}
                    />
                </DraftVerbs>
            )}
            {notice}
            <Notice className="mt-1.5">{said}</Notice>
        </DraftCardFrame>
    )
}

/**
 * The form of a new comment on a line of the diff, as `canopy review edit RUN --add PATH:LINE`: saved as a new
 * version, its card then takes the form's place. `onDone` closes it, saved or not.
 */
export function NewCommentCard({ run, adding, onDone }: { run: number; adding: Adding; onDone: () => void }) {
    const client = useQueryClient()
    return (
        <DraftCardFrame
            waiting
            testId="new-draft-comment"
            header={
                <>
                    <span className="panel-label">New comment</span>
                    <span className="font-mono text-xs break-all text-muted-foreground">
                        {adding.path}:{adding.line}
                    </span>
                </>
            }
        >
            <DraftTextForm
                label={`Comment on ${adding.path}:${adding.line}`}
                initial=""
                save={(text) => addReviewDraftComment(run, adding.path, adding.line, text)}
                onSaved={(saved) => {
                    onDone()
                    void showReviewDraft(client, run, saved)
                }}
                onCancel={onDone}
            />
        </DraftCardFrame>
    )
}

/**
 * A text of the draft in the operator's own words: plain text, held to the bound a draft's text is, empty only where
 * `allowEmpty` says it may be, the body's. Saved through `save`, a new version, which `onSaved` hears.
 */
function DraftTextForm({
    label,
    initial,
    allowEmpty = false,
    save,
    onSaved,
    onCancel,
}: {
    label: string
    initial: string
    allowEmpty?: boolean
    save: (text: string) => Promise<ReviewDraft>
    onSaved: (saved: ReviewDraft) => void
    onCancel: () => void
}) {
    const [text, setText] = useState(initial)
    return (
        <DraftForm
            label={label}
            text={text}
            onText={setText}
            fits={allowEmpty || text.trim() !== ''}
            save={() => save(text)}
            onSaved={onSaved}
            onCancel={onCancel}
        />
    )
}
