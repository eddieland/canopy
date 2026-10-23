import { useMutation, useQueryClient } from '@tanstack/react-query'
import { ChevronDown, Eye, EyeOff } from 'lucide-react'
import { useState } from 'react'

import { dismissFinding, dismissReviewFinding, refreshFindings, refreshReview } from '@/api/mutations'
import type { DismissalReason, ReviewDismissed, ReviewFinding } from '@/api/types'
import { Notice } from '@/components/notice'
import { Button } from '@/components/ui/button'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { dismissedText, reviewDismissedText } from '@/lib/outcomes'

/**
 * Why a review's finding may be dismissed, in the order its menu lists them (DESIGN §21): each reason, its words, and
 * what it means. A `wrong` dismissal is the reviewer's noise; the other two are findings that held.
 */
export const DISMISSAL_REASONS: readonly { reason: DismissalReason; label: string; hint: string }[] = [
    { reason: 'wrong', label: 'wrong', hint: 'It does not hold: the reviewer misread the code' },
    { reason: 'intentional', label: 'intentional', hint: 'It holds, and the change means it to' },
    { reason: 'not_worth_it', label: 'not worth it', hint: 'It holds, and is not worth the fix' },
]

/** A dismissed finding's chip: `dismissed`, then why, when the operator said (`dismissed: not worth it`). */
export function dismissedLabel(finding: ReviewFinding): string {
    const why = DISMISSAL_REASONS.find((r) => r.reason === finding.dismissed_reason)
    return why === undefined ? 'dismissed' : `dismissed: ${why.label}`
}

/**
 * `canopy dismiss` on one of a chore's open findings (DESIGN §19): `button` dismisses it, keeping it off the attention
 * list until the chore stops reporting it, or undoes that, listing it again; `notice` says what the last click did, or
 * why it was refused, and is nothing before one. The button sits in the finding's head line, the notice under it.
 */
export function useDismissFinding(chore: string, finding: string, dismissed: boolean) {
    const client = useQueryClient()
    return useDismiss({
        dismissed,
        act: async ({ undo }) => dismissedText(await dismissFinding(chore, finding, undo)),
        refresh: () => refreshFindings(client, chore),
        labels: ['dismiss', 'undo'],
        titles: [
            'Keep it off the attention list until the chore stops reporting it',
            'List it on the attention list again',
        ],
        testId: finding,
        reasons: false,
    })
}

/**
 * `canopy dismiss review:ID N --reason REASON` on one of a review's findings (DESIGN §21): `button` opens a menu of
 * the reasons (`DISMISSAL_REASONS`), and picking one dismisses it for that reason, so no worker or tick acts on it; on
 * a dismissed finding, it undoes that. `notice` as for a chore's finding. Both undo as `canopy dismiss --undo` does.
 * `words`, on a review with a draft, names the button and says what a click did in the draft's terms, where the
 * dismissal leaves the finding out of the operator's review and taking it back puts it in again (DESIGN §34).
 */
export function useDismissReviewFinding(run: number, finding: number, dismissed: boolean, words?: DismissalWords) {
    const client = useQueryClient()
    return useDismiss({
        dismissed,
        act: async ({ undo, reason }) =>
            (words?.said ?? reviewDismissedText)(await dismissReviewFinding(run, finding, undo, reason)),
        refresh: () => refreshReview(client, run),
        labels: words?.labels ?? ['dismiss', 'undo'],
        titles: words?.titles ?? ['Say why, and no worker or tick acts on it', 'Hand it to a resumed worker again'],
        testId: `finding-${finding}`,
        reasons: true,
    })
}

/** What a review finding's dismissal button is called and says, each pair as `[dismiss, undo]`. */
export interface DismissalWords {
    /** The button's label. */
    labels: [string, string]
    /** Its title, shown on hover. */
    titles: [string, string]
    /** What a click did, from the server's answer. */
    said: (dismissed: ReviewDismissed) => string
}

// What one click asks: a dismissal, for a reason when a review's, or with `undo` the taking back of one.
interface Act {
    undo: boolean
    reason?: DismissalReason
}

interface Dismissal {
    dismissed: boolean
    act: (asked: Act) => Promise<string>
    refresh: () => Promise<void>
    labels: [string, string]
    titles: [string, string]
    testId: string
    // Whether a dismissal says why, picked from a menu: a review's does, a chore's does not.
    reasons: boolean
}

function useDismiss({ dismissed, act, refresh, labels, titles, testId, reasons }: Dismissal) {
    const [said, setSaid] = useState<string | null>(null)
    const dismiss = useMutation({
        mutationFn: act,
        onSuccess: (text) => {
            setSaid(text)
            void refresh()
        },
    })
    const which = dismissed ? 1 : 0
    const menu = reasons && !dismissed
    const trigger = (
        <Button
            variant="ghost"
            size="xs"
            // Negative margins keep the head line as tall as it is without the button.
            className="-my-1 text-muted-foreground"
            title={titles[which]}
            onClick={menu ? undefined : () => dismiss.mutate({ undo: dismissed })}
            disabled={dismiss.isPending}
            data-testid={`${dismissed ? 'undismiss' : 'dismiss'}-${testId}`}
        >
            {dismissed ? <Eye /> : <EyeOff />}
            {labels[which]}
            {menu && <ChevronDown aria-hidden />}
        </Button>
    )
    const button = menu ? (
        <DropdownMenu>
            <DropdownMenuTrigger asChild>{trigger}</DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="min-w-56">
                {DISMISSAL_REASONS.map(({ reason, label, hint }) => (
                    <DropdownMenuItem
                        key={reason}
                        onSelect={() => dismiss.mutate({ undo: false, reason })}
                        data-testid={`dismiss-${testId}-${reason}`}
                    >
                        <span className="flex flex-col">
                            <span>{label}</span>
                            <span className="text-xs text-muted-foreground">{hint}</span>
                        </span>
                    </DropdownMenuItem>
                ))}
            </DropdownMenuContent>
        </DropdownMenu>
    ) : (
        trigger
    )
    const notice = <Notice error={dismiss.error}>{said}</Notice>
    return { button, notice }
}
