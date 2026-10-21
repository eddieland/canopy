import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ChevronDown, ScanSearch, Square } from 'lucide-react'
import { useId, useState } from 'react'

import { refreshReviewRequests, requestReview, stopReview } from '@/api/mutations'
import { personasQuery } from '@/api/queries'
import type { PersonaList, ReviewRequest } from '@/api/types'
import { Age } from '@/components/age'
import { Input, Textarea } from '@/components/input'
import { Notice } from '@/components/notice'
import { SendKeycap } from '@/components/send-keycap'
import { Button } from '@/components/ui/button'
import {
    DropdownMenu,
    DropdownMenuCheckboxItem,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { reviewPersonasText, reviewRequestedText, reviewStoppedText } from '@/lib/outcomes'
import { pullRequestUrl } from '@/lib/pull-request-label'
import { useSendKeys } from '@/lib/send-key'
import { cn } from '@/lib/utils'

// The operator's bound (DESIGN §22): the server refuses more, after stripping, rather than cut it.
const MAX_NOTES = 4000

/**
 * `canopy start URL --review --notes TEXT --persona NAME` from the reviews page (DESIGN §21, §22, §31): a PR the loop
 * does not own, by its URL, with what its reviewer should know, and the personas to review it in, one review each,
 * or none for `[personas] reviewer`'s. canopy reviews it once, at its head, in whichever of the workspace's
 * repositories it is in. Nothing is posted on the PR, and nothing is reviewed now: the next tick does it.
 */
export function ReviewRequestForm({ className }: { className?: string }) {
    const client = useQueryClient()
    const id = useId()
    const sendKeys = useSendKeys()
    const [url, setUrl] = useState('')
    const [notes, setNotes] = useState('')
    const [chosen, setChosen] = useState<readonly string[]>([])
    const [said, setSaid] = useState<string | null>(null)
    const { data: personas } = useQuery(personasQuery)
    // A link into a GitHub PR, such as one of its threads, names the PR: the server takes only its own address.
    const target = pullRequestUrl(url.trim()) ?? url.trim()
    const request = useMutation({
        mutationFn: () => requestReview(target, notes.trim(), chosen),
        onSuccess: (requested) => {
            setSaid(reviewRequestedText(target, requested, notes.trim() !== '', chosen.length > 0))
            setUrl('')
            setNotes('')
            setChosen([])
            void refreshReviewRequests(client)
        },
    })
    const ready = url.trim() !== '' && !request.isPending
    return (
        <form
            className={cn('flex flex-col gap-2 p-3', className)}
            data-testid="review-request-form"
            onSubmit={(event) => {
                event.preventDefault()
                if (ready) {
                    request.mutate()
                }
            }}
        >
            <p className="text-sm text-muted-foreground">
                Have canopy review a PR the loop does not own, such as a coworker&apos;s. Its review stays here; nothing
                is posted on the PR.
            </p>
            <div className="flex flex-wrap items-center gap-2">
                <Input
                    aria-label="PR URL"
                    placeholder="https://github.com/org/repo/pull/123"
                    className="min-w-64 flex-1 font-mono text-xs"
                    value={url}
                    onChange={(event) => setUrl(event.target.value)}
                    data-testid="review-request-url"
                />
                <Button
                    type="submit"
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
            <div className="flex flex-wrap items-center gap-2">
                <span className="panel-label" aria-hidden>
                    Persona
                </span>
                <PersonasMenu personas={personas} chosen={chosen} disabled={request.isPending} onChange={setChosen} />
                {chosen.length > 1 && (
                    <span className="text-xs text-muted-foreground">one review in each, side by side</span>
                )}
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
            <Notice error={request.error}>{said}</Notice>
        </form>
    )
}

/**
 * The personas a review request names, as `--persona NAME` given once for each: a menu of every persona a run could
 * get, any number checked, or none for `[personas] reviewer`'s, which the trigger names. A persona canopy would refuse
 * to run is shown, disabled, with why.
 */
function PersonasMenu({
    personas,
    chosen,
    disabled,
    onChange,
}: {
    personas: PersonaList | undefined
    chosen: readonly string[]
    disabled: boolean
    onChange: (chosen: readonly string[]) => void
}) {
    const shown = chosen.length > 0 ? chosen.join(', ') : `${personas?.reviewer ?? 'canopy'} (default)`
    return (
        <DropdownMenu>
            <DropdownMenuTrigger asChild>
                <Button
                    variant="outline"
                    size="xs"
                    className="font-mono"
                    disabled={disabled || personas === undefined}
                    aria-label={`Persona: ${shown}`}
                    title="canopy start URL --review --persona NAME"
                    data-testid="review-request-personas"
                >
                    {shown}
                    <ChevronDown aria-hidden />
                </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start">
                {personas?.personas.map((p) => (
                    <DropdownMenuCheckboxItem
                        key={p.name}
                        className="font-mono text-xs"
                        checked={chosen.includes(p.name)}
                        disabled={p.error !== null}
                        title={p.error ?? undefined}
                        // Kept open, so several can be checked for a review in each.
                        onSelect={(event) => event.preventDefault()}
                        onCheckedChange={(checked) =>
                            onChange(checked ? [...chosen, p.name] : chosen.filter((name) => name !== p.name))
                        }
                    >
                        {p.name}
                    </DropdownMenuCheckboxItem>
                ))}
                <DropdownMenuSeparator />
                <DropdownMenuItem disabled={chosen.length === 0} onSelect={() => onChange([])}>
                    Use the default
                </DropdownMenuItem>
            </DropdownMenuContent>
        </DropdownMenu>
    )
}

/**
 * A PR's review request on its page: open, with `Stop`, which ends it as `canopy stop URL` does, or how it ended, and
 * the personas and notes it gave the reviewer. Nothing when the operator never asked for the PR to be reviewed.
 */
export function ReviewRequestStatus({
    url,
    request,
    className,
}: {
    url: string
    request: ReviewRequest | null
    className?: string
}) {
    const client = useQueryClient()
    const [said, setSaid] = useState<string | null>(null)
    const stop = useMutation({
        mutationFn: () => stopReview(url),
        onSuccess: (stopped) => {
            setSaid(reviewStoppedText(url, stopped))
            void refreshReviewRequests(client)
        },
    })
    if (request === null) {
        return null
    }
    const open = request.ended_at === null
    return (
        <div className={cn('flex flex-col gap-2 p-3', className)} data-testid="review-request">
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm">
                {open ? (
                    <span>
                        Requested <Age at={request.created_at} variant="ago" /> ({request.channel}). canopy reviews its
                        head once, in the repository it is in, and the request ends with that review.
                    </span>
                ) : (
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
            </div>
            {request.personas.length > 0 && (
                <p className="text-sm" data-testid="review-request-personas">
                    {reviewPersonasText(request.personas)}
                </p>
            )}
            {request.notes !== null && (
                <div className="flex flex-col gap-1" data-testid="review-request-notes">
                    <span className="panel-label">Your notes for the reviewer</span>
                    <p className="text-sm break-words whitespace-pre-wrap">{request.notes}</p>
                </div>
            )}
            <Notice error={stop.error}>{said}</Notice>
        </div>
    )
}
