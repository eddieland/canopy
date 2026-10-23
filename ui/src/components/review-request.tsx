import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from '@tanstack/react-router'
import { ScanSearch, Square } from 'lucide-react'
import { useId, useState } from 'react'

import { refreshReviewRequests, requestReview, stopReview } from '@/api/mutations'
import { personasQuery } from '@/api/queries'
import type { ReviewRequest } from '@/api/types'
import { Age } from '@/components/age'
import { Disclosure } from '@/components/disclosure'
import { Input, Textarea } from '@/components/input'
import { Notice } from '@/components/notice'
import { PersonasMenu } from '@/components/personas-menu'
import { SendKeycap } from '@/components/send-keycap'
import { Button } from '@/components/ui/button'
import { Collapsible, CollapsibleContent } from '@/components/ui/collapsible'
import { reviewPersonasText, reviewRequestedText, reviewStoppedText } from '@/lib/outcomes'
import { pullRequestUrl } from '@/lib/pull-request-label'
import { usablePersonas, useReviewPersonas } from '@/lib/review-personas'
import { useSendKeys } from '@/lib/send-key'
import { cn } from '@/lib/utils'

// The operator's bound (DESIGN §22): the server refuses more, after stripping, rather than cut it.
const MAX_NOTES = 4000

// What an open request does: one review, or one in each of its personas.
const ONCE = 'canopy reviews its head once, in the repository it is in, and the request ends with that review.'
const SEVERAL =
    'canopy reviews its head once in each persona, in the repository it is in, and the request ends once each has.'

/**
 * `canopy start URL --review --notes TEXT --persona NAME` from the reviews page (DESIGN §21, §22, §31), compact as a
 * ticket's `StartTicket` is: a PR the loop does not own, by its URL, an outline `Review`, and what its reviewer should
 * know, always open since the operator writes notes often; the personas to review it in, one review each, or none for
 * `[personas] reviewer`'s, are under `Show persona`. The personas start as those the operator prefers in Settings,
 * which the disclosure's line names while it is closed. canopy reviews it once, at its head, in whichever of the
 * workspace's repositories it is in, and the form opens the PR's page, where the request stands. Its review becomes a
 * draft the operator may publish as their own; nothing posts until they do, and nothing is reviewed now: the next tick
 * does it.
 */
export function ReviewRequestForm({ className }: { className?: string }) {
    const client = useQueryClient()
    const navigate = useNavigate()
    const id = useId()
    const sendKeys = useSendKeys()
    const [url, setUrl] = useState('')
    const [notes, setNotes] = useState('')
    const [more, setMore] = useState(false)
    // The personas picked for this request alone, or null for the operator's preferred ones, as Settings has them now.
    const [picked, setPicked] = useState<readonly string[] | null>(null)
    const { data: personas } = useQuery(personasQuery)
    const preferred = useReviewPersonas()
    const chosen = picked ?? usablePersonas(preferred, personas)
    // A link into a GitHub PR, such as one of its threads, names the PR: the server takes only its own address.
    const target = pullRequestUrl(url.trim()) ?? url.trim()
    const request = useMutation({
        mutationFn: () => requestReview(target, notes.trim(), chosen),
        onSuccess: () => {
            void refreshReviewRequests(client)
            void navigate({ to: '/pull-requests/pr', search: { url: target } })
        },
    })
    const ready = url.trim() !== '' && !request.isPending
    return (
        <form
            className={cn('flex flex-col gap-2 p-3', className)}
            aria-label="Review a PR"
            data-testid="review-request-form"
            onSubmit={(event) => {
                event.preventDefault()
                if (ready) {
                    request.mutate()
                }
            }}
        >
            <div className="flex flex-wrap items-center gap-2">
                <Input
                    aria-label="PR URL"
                    placeholder="https://github.com/org/repo/pull/123"
                    className="max-w-lg min-w-64 flex-1 font-mono text-xs"
                    value={url}
                    onChange={(event) => setUrl(event.target.value)}
                    data-testid="review-request-url"
                />
                <Button
                    type="submit"
                    variant="outline"
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
            <div className="flex flex-col gap-1.5">
                <label className="panel-label" htmlFor={`${id}-notes`}>
                    Notes for the reviewer (optional)
                </label>
                <Textarea
                    id={`${id}-notes`}
                    className="min-h-16 text-xs"
                    value={notes}
                    maxLength={MAX_NOTES}
                    onChange={(event) => setNotes(event.target.value)}
                    onKeyDown={sendKeys.onKeyDown}
                    placeholder="What the author asked for, or the part of the change that worries you"
                    data-testid="review-request-notes"
                />
            </div>
            <Collapsible open={more} onOpenChange={setMore} className="flex flex-col gap-2">
                <span className="flex flex-wrap items-center gap-x-2">
                    <Disclosure open={more} what="persona" className="-ml-2" />
                    {!more && (
                        <span className="text-xs text-muted-foreground" data-testid="review-request-chosen">
                            {chosenText(chosen, picked === null, personas?.reviewer)}
                        </span>
                    )}
                </span>
                <CollapsibleContent className="flex flex-col gap-2">
                    <div className="flex flex-wrap items-center gap-2">
                        <span className="panel-label" aria-hidden>
                            Persona
                        </span>
                        <PersonasMenu
                            personas={personas}
                            chosen={chosen}
                            disabled={request.isPending}
                            onChange={setPicked}
                            title="canopy start URL --review --persona NAME"
                            testId="review-request-personas"
                        />
                        {picked === null && chosen.length > 0 && (
                            <span className="text-xs text-muted-foreground">as Settings prefers</span>
                        )}
                        {chosen.length > 1 && (
                            <span className="text-xs text-muted-foreground">one review in each, side by side</span>
                        )}
                    </div>
                </CollapsibleContent>
            </Collapsible>
            <Notice error={request.error}>
                For a PR the loop does not own, such as a coworker&apos;s. Its review is a draft you may publish, word
                for word, as your own; nothing posts until you do.
            </Notice>
        </form>
    )
}

// What a closed form reviews in: the personas chosen, those Settings prefers, or the config's reviewer's.
function chosenText(chosen: readonly string[], preferred: boolean, reviewer: string | undefined): string {
    if (chosen.length === 0) {
        return `in ${reviewer ?? 'canopy'}, the default`
    }
    return `in ${chosen.join(', ')}${preferred ? ', as Settings prefers' : ''}`
}

/**
 * A PR's review request on its page, in the foot of its Pull request panel: open, with `Stop`, which ends it as
 * `canopy stop URL` does, or how it ended, and the personas and notes it gave the reviewer. While none is open on a
 * PR the loop does not own, `Review this PR`, or `Review again` once it has a review or a request that ended, asks
 * for one as `canopy start URL --review` does, in the personas its menu names: the ended request's, else those
 * Settings prefers. Nothing for one of the loop's own PRs never asked to be reviewed, which the server refuses
 * (`loop_pr`).
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
        mutationFn: () => requestReview(url, '', chosen),
        onSuccess: (requested) => {
            setSaid(reviewRequestedText(url, requested, false, chosen.length > 0))
            setPicked(null)
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
            {request !== null && request.personas.length > 0 && (
                <p className="text-sm" data-testid="review-request-personas">
                    {reviewPersonasText(request.personas)}
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
