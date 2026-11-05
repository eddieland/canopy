import { useQuery } from '@tanstack/react-query'
import { useMatchRoute, useSearch } from '@tanstack/react-router'
import { useEffect, useEffectEvent, useState } from 'react'

import { pullRequestQuery } from '@/api/queries'
import { ReviewRequestForm } from '@/components/review-request'
import { Dialog, DialogContent, DialogDescription, DialogTitle } from '@/components/ui/dialog'
import { pullRequestUrl } from '@/lib/pull-request-label'
import { dropReviewRequestDraft, keepReviewRequestDraft, readReviewRequestDraft } from '@/lib/review-request-draft'
import type { ReviewRequestDraft } from '@/lib/review-request-draft'
import { dialogOpen, isBareKey, isTextField } from '@/lib/shortcut'
import { cn } from '@/lib/utils'

/**
 * The Review a PR dialog (ui/DESIGN.md, The review dialog): the reviews page's form (`ReviewRequestForm`) from any
 * page, placed as the jump palette is. `R`, with no modifier, from anywhere but a text field or the plan editor, opens
 * it, with the PR's URL filled in on a PR's page while no review request of it is open; so does pasting a GitHub PR's
 * URL, or a link into one, anywhere outside a field, with that URL filled in. Pasting anything else does nothing.
 * Neither opens it over another dialog, the jump palette's or 2048's. What is written or pasted in it is kept in this
 * tab (`src/lib/review-request-draft.ts`) across closing and opening it again, until a request goes through, when it
 * closes and the form opens the PR's page; a URL the page filled in is not kept, so it never follows the operator off
 * that page.
 */
export function ReviewDialog() {
    // What the form opened with, while it is open.
    const [opened, setOpened] = useState<ReviewRequestDraft | null>(null)
    const matchRoute = useMatchRoute()
    const searchUrl = useSearch({ strict: false, select: (search) => search.url })
    const onPage = matchRoute({ to: '/pull-requests/pr' }) === false ? undefined : searchUrl
    // The PR's page has read it already; one whose request is open, as it is once the dialog's request goes through,
    // has nothing to ask, so R opens on what is kept rather than on what was just sent.
    const { data: shown } = useQuery({ ...pullRequestQuery(onPage ?? ''), enabled: onPage !== undefined })
    const here = shown?.pull_request.review_request?.ended_at === null ? undefined : onPage

    // A URL pasted replaces the one kept, and is kept in its place; one the page fills in shows only while it is open,
    // until it is edited. The notes, personas, and model stay as written.
    function open(url: string | undefined, keep: boolean) {
        const kept = readReviewRequestDraft()
        const draft = url === undefined ? kept : { ...kept, url }
        if (keep) {
            keepReviewRequestDraft(draft)
        }
        setOpened(draft)
    }

    const onKey = useEffectEvent((event: KeyboardEvent) => {
        if (isBareKey('r', event) && !isTextField(event.target) && !dialogOpen()) {
            event.preventDefault()
            open(here, false)
        }
    })
    const onPaste = useEffectEvent((event: ClipboardEvent) => {
        if (event.defaultPrevented || isTextField(event.target) || dialogOpen()) {
            return
        }
        const text = event.clipboardData?.getData('text/plain').trim() ?? ''
        if (/\s/u.test(text) || pullRequestUrl(text) === null) {
            return
        }
        event.preventDefault()
        open(text, true)
    })
    useEffect(() => {
        globalThis.addEventListener('keydown', onKey)
        globalThis.addEventListener('paste', onPaste)
        return () => {
            globalThis.removeEventListener('keydown', onKey)
            globalThis.removeEventListener('paste', onPaste)
        }
    }, [])

    return (
        <Dialog
            open={opened !== null}
            onOpenChange={(isOpen) => {
                if (!isOpen) {
                    setOpened(null)
                }
            }}
        >
            <DialogContent className="max-w-xl" data-testid="review-dialog">
                {/* A panel's header, as on the reviews page, inside the box's border. */}
                <div
                    className={cn(
                        'flex min-h-9 items-center border-b bg-surface-raised/50 px-3 py-0.5',
                        'rounded-t-[calc(var(--radius-md)-1px)]',
                    )}
                >
                    <DialogTitle className="panel-label font-medium text-foreground">Review a PR</DialogTitle>
                </div>
                <DialogDescription className="sr-only">
                    Have canopy review a PR the loop does not own: its URL, notes for the reviewer, and its personas and
                    model
                </DialogDescription>
                {opened !== null && (
                    <ReviewRequestForm
                        draft={opened}
                        onDraft={keepReviewRequestDraft}
                        onRequested={() => {
                            dropReviewRequestDraft()
                            setOpened(null)
                        }}
                        focus
                        notice
                    />
                )}
            </DialogContent>
        </Dialog>
    )
}
