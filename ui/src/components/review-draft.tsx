import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Link } from '@tanstack/react-router'
import { GitPullRequestDraft, Pencil, Send, Trash2 } from 'lucide-react'
import { useId, useState } from 'react'
import type { SubmitEvent } from 'react'

import {
    addReviewDraftComment,
    dropReviewDraftComment,
    editReviewDraftBody,
    editReviewDraftComment,
    publishReviewDraft,
    showReviewDraft,
} from '@/api/mutations'
import type { ReviewDraft, ReviewDraftComment } from '@/api/types'
import { Textarea } from '@/components/input'
import { MemoryText } from '@/components/memory-text'
import { Notice } from '@/components/notice'
import { Panel, PanelFooter, PanelHeader } from '@/components/panel'
import { ListRow } from '@/components/rows'
import { SendKeycap } from '@/components/send-keycap'
import { Chip } from '@/components/status'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { MAX_DRAFT_CHARS, draftChars } from '@/lib/drafts'
import { reviewDraftEditedText, reviewDraftPublishedText } from '@/lib/outcomes'
import { REVIEW_DRAFT_TONE, commentAnchor, editable, versionBy } from '@/lib/review-drafts'
import type { Adding } from '@/lib/review-drafts'
import { shortSha } from '@/lib/reviews'
import { useSendKeys } from '@/lib/send-key'
import { cn } from '@/lib/utils'

// What the draft is, around the commit the review read.
const INTRO = [
    'What canopy would post on the PR in your name, word for word and unmarked: one comment review on ',
    " that approves nothing. The reviewer wrote it from the PR's text, so read it before you publish it.",
] as const

/**
 * A review of a PR the loop does not own as the comment review canopy would post in the operator's name (DESIGN §34):
 * its newest version word for word, the body here and each comment on its line of the diff, every hidden character
 * named, since the reviewer wrote it from the PR's text. While it waits, the body is edited here, each comment on its
 * card, and a comment added on any line of the diff; each change is a new version, as `canopy review edit` makes.
 * Publishing posts the version shown, named by its hash, as one comment review on the commit the review read: left
 * pending on GitHub for the operator to submit there, or submitted now when they tick it, as `--submit` does. A staged
 * one says where to finish it, a published one links to it. With no diff kept, its comments are listed here.
 * `onFollow` hears a link followed to a comment's card, by its file's index in the diff.
 */
export function ReviewDraftPanel({
    run,
    prUrl,
    sha,
    draft,
    hasDiff,
    onFollow,
}: {
    run: number
    prUrl: string
    sha: string
    draft: ReviewDraft
    hasDiff: boolean
    onFollow: (file: number) => void
}) {
    const client = useQueryClient()
    const [editingBody, setEditingBody] = useState(false)
    const [said, setSaid] = useState<string | null>(null)
    const open = editable(draft)
    return (
        <Panel data-testid="review-draft">
            <PanelHeader label="Draft review">
                <Chip tone={REVIEW_DRAFT_TONE[draft.status]} word={draft.status} />
                <span className="ml-auto font-mono text-2xs text-muted-foreground" title="The hash a publish carries">
                    version {draft.version}, {draft.hash}
                </span>
            </PanelHeader>
            <div className="flex flex-col gap-2 p-3 text-sm">
                <p className="text-muted-foreground">
                    {INTRO[0]}
                    <span className="font-mono text-xs">{shortSha(sha)}</span>
                    {INTRO[1]}
                    {` Version ${draft.version}: ${draft.change}, ${versionBy(draft)}.`}
                </p>
                {draft.moved_head !== null && (
                    <p className="text-status-blocked" data-testid="draft-head-moved">
                        {"The PR's head is "}
                        <span className="font-mono text-xs">{shortSha(draft.moved_head)}</span>
                        {' now: its comments would show as outdated, on the commit the review read.'}
                    </p>
                )}
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
            <CommentList run={run} draft={draft} hasDiff={hasDiff} onFollow={onFollow} />
            <VersionList draft={draft} />
            <PublishFooter run={run} prUrl={prUrl} draft={draft} said={said} onSaid={setSaid} />
        </Panel>
    )
}

/**
 * The draft's comments, each a row linking to its card on the diff, where it is edited or dropped; with no diff kept,
 * the rows are the cards themselves. A line under them says how to add one.
 */
function CommentList({
    run,
    draft,
    hasDiff,
    onFollow,
}: {
    run: number
    draft: ReviewDraft
    hasDiff: boolean
    onFollow: (file: number) => void
}) {
    const count = draft.comments.length
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
                        <ListRow key={c.number} kind="review-finding" className="py-2 text-sm">
                            <span className="readout text-xs text-muted-foreground">{c.number}</span>
                            <Chip className="justify-center">
                                {c.finding === null ? 'yours' : `finding ${c.finding}`}
                            </Chip>
                            {/* A router link, not a bare `#` href, which the page's <base> would send to the root. */}
                            <Link
                                to="/reviews/$id"
                                params={{ id: String(run) }}
                                hash={commentAnchor(c.number)}
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
 * Publishing the version shown, as `canopy review publish RUN HASH`: staged by default, a pending review for the
 * operator to submit on GitHub, or submitted now when they tick it. A draft staged, published, or of unknown outcome
 * says so instead, and where to look.
 */
function PublishFooter({
    run,
    prUrl,
    draft,
    said,
    onSaid,
}: {
    run: number
    prUrl: string
    draft: ReviewDraft
    said: string | null
    onSaid: (said: string) => void
}) {
    const client = useQueryClient()
    const id = useId()
    const [submit, setSubmit] = useState(false)
    const publish = useMutation({
        mutationFn: () => publishReviewDraft(run, draft.hash, submit),
        onSuccess: (published) => {
            onSaid(reviewDraftPublishedText(run, prUrl, published))
            void showReviewDraft(client, run, published.draft)
        },
    })
    const empty = draft.body === '' && draft.comments.length === 0
    return (
        <PanelFooter>
            {editable(draft) && (
                <span className="flex flex-wrap items-center gap-x-3 gap-y-2">
                    <Button
                        onClick={() => publish.mutate()}
                        disabled={publish.isPending || empty}
                        variant={submit ? 'default' : 'outline'}
                        title={`canopy review publish ${run} ${draft.hash}${submit ? ' --submit' : ''}`}
                    >
                        {submit ? <Send /> : <GitPullRequestDraft />}
                        {publishLabel(draft.version, { submit, pending: publish.isPending })}
                    </Button>
                    <span className="flex items-center gap-2 text-sm">
                        <Checkbox
                            id={`${id}-submit`}
                            checked={submit}
                            onCheckedChange={(checked) => setSubmit(checked === true)}
                            disabled={publish.isPending}
                        />
                        <label htmlFor={`${id}-submit`}>Submit it on GitHub now</label>
                    </span>
                    <span className="text-xs text-muted-foreground">
                        {submit
                            ? 'canopy submits it as your comment review, now and once: a draft publishes one version.'
                            : 'It waits on GitHub as a pending review only you see, until you submit it there.'}
                    </span>
                </span>
            )}
            {draft.status === 'staged' && (
                <p className="text-sm" data-testid="draft-staged">
                    It waits in the review you staged. Submit or delete it{' '}
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
                    Published as your review{' '}
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
            <Notice error={publish.error}>{said}</Notice>
        </PanelFooter>
    )
}

// What the publish button says: what it does, ticked to submit or not, and that it is doing it while it is.
function publishLabel(version: number, { submit, pending }: { submit: boolean; pending: boolean }): string {
    if (submit) {
        return pending ? 'Publishing…' : `Publish version ${version}`
    }
    return pending ? 'Starting the review…' : 'Start the review on GitHub'
}

/**
 * One comment of the draft, at its line of the diff: its number, the finding it was made from or that it is the
 * operator's, and its text, plain, every hidden character named. While the draft waits, Edit puts its text in a form
 * and Drop leaves it out, each a new version; dropping one made from a finding leaves the finding as it is.
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
        <article
            id={commentAnchor(comment.number)}
            className="scroll-mt-16 rounded-md border border-accent/40 bg-surface p-3 text-sm"
            data-testid="draft-comment"
        >
            <header className="flex flex-wrap items-center gap-2">
                <span className="panel-label">Comment {comment.number}</span>
                <Chip>{comment.finding === null ? 'yours' : `from finding ${comment.finding}`}</Chip>
                <span className="font-mono text-xs break-all text-muted-foreground">
                    {comment.path}:{comment.line}
                </span>
                {open && !editing && (
                    <span className="ml-auto flex items-center gap-1">
                        <Button
                            size="xs"
                            variant="ghost"
                            className="-my-1 text-muted-foreground"
                            onClick={() => setEditing(true)}
                            disabled={drop.isPending}
                            title={`canopy review edit ${run} --comment ${comment.number} --text TEXT`}
                        >
                            <Pencil />
                            edit
                        </Button>
                        <Button
                            size="xs"
                            variant="ghost"
                            className="-my-1 text-muted-foreground"
                            onClick={() => drop.mutate()}
                            disabled={drop.isPending}
                            title={`canopy review edit ${run} --drop ${comment.number}`}
                        >
                            <Trash2 />
                            drop
                        </Button>
                    </span>
                )}
            </header>
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
            <Notice error={drop.error} className="mt-1.5">
                {said}
            </Notice>
        </article>
    )
}

/**
 * The form of a new comment on a line of the diff, as `canopy review edit RUN --add PATH:LINE`: saved as a new
 * version, its card then takes the form's place. `onDone` closes it, saved or not.
 */
export function NewCommentCard({ run, adding, onDone }: { run: number; adding: Adding; onDone: () => void }) {
    const client = useQueryClient()
    return (
        <article className="rounded-md border border-accent/40 bg-surface p-3 text-sm" data-testid="new-draft-comment">
            <header className="flex flex-wrap items-center gap-2">
                <span className="panel-label">New comment</span>
                <span className="font-mono text-xs break-all text-muted-foreground">
                    {adding.path}:{adding.line}
                </span>
            </header>
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
        </article>
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
    const id = useId()
    const sendKeys = useSendKeys()
    const [text, setText] = useState(initial)
    const edit = useMutation({ mutationFn: () => save(text), onSuccess: onSaved })
    const chars = draftChars(text)
    const fits = (allowEmpty || text.trim() !== '') && chars <= MAX_DRAFT_CHARS

    function submit(event: SubmitEvent<HTMLFormElement>) {
        event.preventDefault()
        if (fits && !edit.isPending) {
            edit.mutate()
        }
    }

    return (
        <form onSubmit={submit} aria-label={label} className="mt-1.5 flex flex-col gap-2">
            <span className="flex items-baseline justify-between gap-3">
                <label className="panel-label" htmlFor={`${id}-text`}>
                    In your words
                </label>
                <span
                    className={cn(
                        'readout text-xs text-muted-foreground',
                        chars > MAX_DRAFT_CHARS && 'text-status-failed',
                    )}
                >
                    {chars} of {MAX_DRAFT_CHARS}
                </span>
            </span>
            <Textarea
                id={`${id}-text`}
                value={text}
                onChange={(event) => setText(event.target.value)}
                onKeyDown={sendKeys.onKeyDown}
                spellCheck
                // oxlint-disable-next-line jsx-a11y/no-autofocus -- the form opens on the operator's click, to type in.
                autoFocus
                className="min-h-20"
            />
            <span className="flex flex-wrap items-center gap-2">
                <Button
                    type="submit"
                    size="sm"
                    disabled={edit.isPending || !fits}
                    aria-keyshortcuts={sendKeys.shortcut}
                >
                    Save
                    <SendKeycap keys={sendKeys.shortcut} />
                </Button>
                <Button type="button" size="sm" variant="ghost" onClick={onCancel} disabled={edit.isPending}>
                    Cancel
                </Button>
            </span>
            <Notice error={edit.error} />
        </form>
    )
}
