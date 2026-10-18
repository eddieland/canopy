import { useMutation, useQueryClient } from '@tanstack/react-query'
import { ScanSearch, Square } from 'lucide-react'
import { useState } from 'react'

import { refreshPullRequests, requestReview, stopReview } from '@/api/mutations'
import type { ReviewRequest } from '@/api/types'
import { Age } from '@/components/age'
import { Input } from '@/components/input'
import { Notice } from '@/components/notice'
import { Button } from '@/components/ui/button'
import { reviewRequestedText, reviewStoppedText } from '@/lib/outcomes'
import { cn } from '@/lib/utils'

/**
 * `canopy start URL --review` from the reviews page (DESIGN §21, §22): a PR the loop does not own, by its URL.
 * canopy reviews it once, at its head, in whichever of the workspace's repositories it is in. Nothing is posted on the
 * PR, and nothing is reviewed now: the next tick does it.
 */
export function ReviewRequestForm({ className }: { className?: string }) {
    const client = useQueryClient()
    const [url, setUrl] = useState('')
    const [said, setSaid] = useState<string | null>(null)
    const request = useMutation({
        mutationFn: () => requestReview(url.trim()),
        onSuccess: (requested) => {
            setSaid(reviewRequestedText(url.trim(), requested))
            setUrl('')
            void refreshPullRequests(client)
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
                    data-testid="review-request-submit"
                >
                    <ScanSearch />
                    Review
                </Button>
            </div>
            <Notice error={request.error} reserve>
                {said}
            </Notice>
        </form>
    )
}

/**
 * A PR's review request on its page: open, with `Stop`, which ends it as `canopy stop URL` does, or how it ended.
 * Nothing when the operator never asked for the PR to be reviewed.
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
            void refreshPullRequests(client)
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
            <Notice error={stop.error} reserve>
                {said}
            </Notice>
        </div>
    )
}
