import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from '@tanstack/react-router'
import { ScanSearch, Square } from 'lucide-react'
import { useId, useState } from 'react'

import { refreshReviewRequests, requestReview, stopReview } from '@/api/mutations'
import { personasQuery } from '@/api/queries'
import type { ReviewRequest } from '@/api/types'
import { Age } from '@/components/age'
import { Input, Textarea } from '@/components/input'
import { Notice } from '@/components/notice'
import { PersonasMenu } from '@/components/personas-menu'
import { ReviewModelMenu } from '@/components/review-model'
import { SendKeycap } from '@/components/send-keycap'
import { Button } from '@/components/ui/button'
import { reviewPersonasText, reviewRequestedText, reviewStoppedText } from '@/lib/outcomes'
import { pullRequestReference, pullRequestUrl } from '@/lib/pull-request-label'
import { usablePersonas, useReviewPersonas } from '@/lib/review-personas'
import { EMPTY_DRAFT } from '@/lib/review-request-draft'
import type { ReviewRequestDraft } from '@/lib/review-request-draft'
import { useSendKeys } from '@/lib/send-key'
import { cn } from '@/lib/utils'

// The operator's bound (DESIGN §22): the server refuses more, after stripping, rather than cut it.
const MAX_NOTES = 4000

// What an open request does: one review, or one in each of its personas.
const ONCE = 'canopy reviews its head once, in the repository it is in, and the request ends with that review.'
const SEVERAL =
    'canopy reviews its head once in each persona, in the repository it is in, and the request ends once each has.'

// A field's label in the form, the same for each: sentence case, no louder than what is written in the field.
const FIELD_LABEL = 'text-xs font-medium'

/**
 * `canopy start URL --review --notes TEXT --persona NAME --model M` from the reviews page (DESIGN §13, §21, §22, §31):
 * one column, every part on its left edge and to its width (ui/DESIGN.md, "A review request"). A PR the loop does not
 * own, by its URL, with the PR's reference under it once canopy would take it, or a line saying it would not; then what
 * its reviewer should know; then who reviews it, on one row: the personas to review it in, one review each, or none
 * for `[personas] reviewer`'s, and the model its reviews run on, config's by default; and at the row's end `Review`,
 * the form's primary. The personas start as those the operator prefers in Settings, which the row says. canopy reviews
 * it once, at its head, in whichever of the workspace's repositories it is in, and the form opens the PR's page, where
 * the request stands. Its review becomes a draft the operator may publish as their own; nothing posts until they do,
 * and nothing is reviewed now: the next tick does it. The reviews page and the Review a PR dialog (`ReviewDialog`),
 * which `R` opens from anywhere, both render it, so the two cannot drift; the dialog's says so on a quiet line, since
 * the reviews page's description already does.
 */
export function ReviewRequestForm({
    className,
    draft = EMPTY_DRAFT,
    onDraft,
    onRequested,
    focus = false,
    notice = false,
}: {
    /** Classes for the form. */
    className?: string
    /** What the form starts with: a draft kept from before, or a PR's URL filled in. Empty by default. */
    draft?: ReviewRequestDraft
    /** Hears each change to what is written or picked, to keep it. */
    onDraft?: (draft: ReviewRequestDraft) => void
    /** Hears a request go through, as the form opens the PR's page. */
    onRequested?: () => void
    /** Whether the form takes the focus as it mounts: the URL field, or the notes once a URL is filled in. */
    focus?: boolean
    /** Whether a quiet line under the form says its review is a draft: the dialog's, where nothing else says so. */
    notice?: boolean
}) {
    const client = useQueryClient()
    const navigate = useNavigate()
    const id = useId()
    const sendKeys = useSendKeys()
    const [url, setUrl] = useState(draft.url)
    const [notes, setNotes] = useState(draft.notes)
    // The personas picked for this request alone, or null for the operator's preferred ones, as Settings has them now.
    const [picked, setPicked] = useState<readonly string[] | null>(draft.picked)
    // The model picked for this request alone, or null for config's.
    const [model, setModel] = useState<string | null>(draft.model)
    // Where the focus starts, as the form mounts: a dialog's own first focus keeps a focus already inside it.
    const [focused] = useState(focus ? (draft.url.trim() === '' ? 'url' : 'notes') : null)

    function change(next: Partial<ReviewRequestDraft>) {
        onDraft?.({ url, notes, picked, model, ...next })
    }
    const { data: personas } = useQuery(personasQuery)
    const preferred = useReviewPersonas()
    const chosen = picked ?? usablePersonas(preferred, personas)
    // A link into a GitHub PR, such as one of its threads, names the PR: the server takes only its own address.
    const target = pullRequestUrl(url.trim()) ?? url.trim()
    const request = useMutation({
        mutationFn: () => requestReview(target, notes.trim(), chosen, model),
        onSuccess: () => {
            void refreshReviewRequests(client)
            onRequested?.()
            void navigate({ to: '/pull-requests/pr', search: { url: target } })
        },
    })
    const ready = url.trim() !== '' && !request.isPending
    return (
        <form
            className={cn('flex max-w-3xl flex-col gap-3 p-3', className)}
            aria-label="Review a PR"
            aria-keyshortcuts="R"
            data-testid="review-request-form"
            onSubmit={(event) => {
                event.preventDefault()
                if (ready) {
                    request.mutate()
                }
            }}
        >
            <div className="flex flex-col gap-1.5">
                <Input
                    // oxlint-disable-next-line jsx-a11y/no-autofocus -- the dialog opens on a key, to type in.
                    autoFocus={focused === 'url'}
                    aria-label="PR URL"
                    aria-describedby={`${id}-ref`}
                    placeholder="https://github.com/org/repo/pull/123"
                    title="R opens this form from any page, and so does pasting a PR's URL"
                    className="font-mono text-xs"
                    value={url}
                    onChange={(event) => {
                        setUrl(event.target.value)
                        change({ url: event.target.value })
                    }}
                    data-testid="review-request-url"
                />
                <PullRequestReference id={`${id}-ref`} url={url.trim()} />
            </div>
            <div className="flex flex-col gap-1.5">
                <label className={FIELD_LABEL} htmlFor={`${id}-notes`}>
                    Notes for the reviewer <span className="font-normal text-muted-foreground">(optional)</span>
                </label>
                <Textarea
                    // oxlint-disable-next-line jsx-a11y/no-autofocus -- the dialog opens on a key, to type in.
                    autoFocus={focused === 'notes'}
                    id={`${id}-notes`}
                    className="min-h-16 text-xs"
                    value={notes}
                    maxLength={MAX_NOTES}
                    onChange={(event) => {
                        setNotes(event.target.value)
                        change({ notes: event.target.value })
                    }}
                    onKeyDown={sendKeys.onKeyDown}
                    placeholder="What the author asked for, or the part of the change that worries you"
                    data-testid="review-request-notes"
                />
            </div>
            {/* Who reviews it, then the primary at the row's end, on the fields' right edge. */}
            <div className="flex flex-wrap items-center gap-x-4 gap-y-2" data-testid="review-request-reviewer">
                <span className="flex flex-wrap items-center gap-2">
                    <span className={FIELD_LABEL} aria-hidden>
                        Persona
                    </span>
                    <PersonasMenu
                        personas={personas}
                        chosen={chosen}
                        disabled={request.isPending}
                        onChange={(next) => {
                            setPicked(next)
                            change({ picked: next })
                        }}
                        title="canopy start URL --review --persona NAME"
                        testId="review-request-personas"
                    />
                    {picked === null && chosen.length > 0 && (
                        <span className="text-xs text-muted-foreground">as Settings prefers</span>
                    )}
                    {chosen.length > 1 && (
                        <span className="text-xs text-muted-foreground">one review in each, side by side</span>
                    )}
                </span>
                <ReviewModelMenu
                    model={model}
                    disabled={request.isPending}
                    onChange={(next) => {
                        setModel(next)
                        change({ model: next })
                    }}
                    testId="review-request-model"
                    labelClassName={FIELD_LABEL}
                />
                <Button
                    type="submit"
                    className="ml-auto"
                    disabled={!ready}
                    title="canopy start URL --review"
                    aria-keyshortcuts={sendKeys.shortcut}
                    data-testid="review-request-submit"
                >
                    <ScanSearch />
                    Review
                    <SendKeycap keys={sendKeys.shortcut} />
                </Button>
            </div>
            <Notice error={request.error}>
                {notice && 'For a PR the loop does not own. Nothing posts until you publish its draft.'}
            </Notice>
        </form>
    )
}

/**
 * What the URL field names, on the line under it, which it always holds so the notes never move as it changes: the
 * PR's reference once canopy would take it, `acme/web#88` as the reviews list writes it, or that it is not a PR's URL,
 * which canopy would refuse, before it is sent; with nothing written, that a link into a PR names it too.
 */
function PullRequestReference({ id, url }: { id: string; url: string }) {
    const reference = url === '' ? null : pullRequestReference(url)
    return (
        <p id={id} className="min-h-4 text-xs text-muted-foreground" data-testid="review-request-ref">
            {url === '' && 'A link into the PR, such as one of its threads, names it too.'}
            {reference !== null && <span className="font-mono text-foreground">{reference}</span>}
            {url !== '' && reference === null && "Not a PR's URL, so canopy would refuse it."}
        </p>
    )
}

/**
 * A PR's review request on its page, in the foot of its Pull request panel: open, with `Stop`, which ends it as
 * `canopy stop URL` does, or how it ended, and the personas, model, and notes it gave the reviewer. While none is open
 * on a PR the loop does not own, `Review this PR`, or `Review again` once it has a review or a request that ended,
 * asks for one as `canopy start URL --review` does, in the personas its menu names: the ended request's, else those
 * Settings prefers; and on the model its model menu names, config's unless one is picked for this request alone.
 * Nothing for one of the loop's own PRs never asked to be reviewed, which the server refuses (`loop_pr`).
 */
export function ReviewRequestStatus({
    url,
    request,
    loopPr,
    reviewed,
    className,
}: {
    url: string
    request: ReviewRequest | null
    loopPr: boolean
    reviewed: boolean
    className?: string
}) {
    const client = useQueryClient()
    const [said, setSaid] = useState<string | null>(null)
    // The personas picked for the next request alone, or null for the ended request's, else Settings'.
    const [picked, setPicked] = useState<readonly string[] | null>(null)
    // The model picked for the next request alone, or null for config's.
    const [model, setModel] = useState<string | null>(null)
    const { data: personas } = useQuery(personasQuery)
    const preferred = useReviewPersonas()
    const before = request === null ? [] : request.personas
    const chosen = picked ?? usablePersonas(before.length > 0 ? before : preferred, personas)
    const stop = useMutation({
        mutationFn: () => stopReview(url),
        onSuccess: (stopped) => {
            setSaid(reviewStoppedText(url, stopped))
            void refreshReviewRequests(client)
        },
    })
    const ask = useMutation({
        mutationFn: () => requestReview(url, '', chosen, model),
        onSuccess: (requested) => {
            setSaid(reviewRequestedText(url, requested, false, chosen.length > 0, model !== null))
            setPicked(null)
            setModel(null)
            void refreshReviewRequests(client)
        },
    })
    const open = request?.ended_at === null
    const asks = !open && !loopPr
    if (request === null && !asks) {
        return null
    }
    return (
        <div className={cn('flex flex-col gap-2 p-3', className)} data-testid="review-request">
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm">
                {request === null && (
                    <span className="text-muted-foreground">
                        Have canopy review its head. Its review is a draft you may publish as your own; nothing posts
                        until you do.
                    </span>
                )}
                {open && (
                    <span>
                        Requested <Age at={request.created_at} variant="ago" /> ({request.channel}).{' '}
                        {request.personas.length > 1 ? SEVERAL : ONCE}
                    </span>
                )}
                {request !== null && !open && (
                    <span className="text-muted-foreground">
                        Your review request ended{' '}
                        {request.ended_at !== null && <Age at={request.ended_at} variant="ago" />}:{' '}
                        <span className="font-mono text-xs">{request.end_reason}</span>.
                    </span>
                )}
                {open && (
                    <Button
                        variant="outline"
                        className="ml-auto"
                        title={`canopy stop ${url}`}
                        onClick={() => stop.mutate()}
                        disabled={stop.isPending}
                        data-testid="review-request-stop"
                    >
                        <Square />
                        Stop
                    </Button>
                )}
                {asks && (
                    <span className="ml-auto flex items-center gap-2">
                        <PersonasMenu
                            personas={personas}
                            chosen={chosen}
                            disabled={ask.isPending}
                            onChange={setPicked}
                            title={`canopy start ${url} --review --persona NAME`}
                            testId="review-request-personas-menu"
                        />
                        <ReviewModelMenu
                            model={model}
                            url={url}
                            disabled={ask.isPending}
                            onChange={setModel}
                            testId="review-request-model-menu"
                        />
                        <Button
                            variant="outline"
                            title={`canopy start ${url} --review`}
                            onClick={() => ask.mutate()}
                            disabled={ask.isPending}
                            data-testid="review-request-ask"
                        >
                            <ScanSearch />
                            {reviewed || request !== null ? 'Review again' : 'Review this PR'}
                        </Button>
                    </span>
                )}
            </div>
            {request !== null && (request.personas.length > 0 || request.model !== null) && (
                <p className="text-sm" data-testid="review-request-personas">
                    {request.personas.length > 0 && reviewPersonasText(request.personas)}
                    {request.personas.length > 0 && request.model !== null && ' '}
                    {request.model !== null && (
                        <span data-testid="review-request-model">
                            Its reviews run on <span className="font-mono text-xs">{request.model}</span>.
                        </span>
                    )}
                </p>
            )}
            {request !== null && request.notes !== null && (
                <div className="flex flex-col gap-1" data-testid="review-request-notes">
                    <span className="panel-label">Your notes for the reviewer</span>
                    <p className="text-sm break-words whitespace-pre-wrap">{request.notes}</p>
                </div>
            )}
            <Notice error={ask.error ?? stop.error}>{said}</Notice>
        </div>
    )
}
