import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Eye, EyeOff } from 'lucide-react'
import { useState } from 'react'

import { dismissFinding, dismissReviewFinding, refreshFindings, refreshReview } from '@/api/mutations'
import type { ReviewDismissed } from '@/api/types'
import { Notice } from '@/components/notice'
import { Button } from '@/components/ui/button'
import { dismissedText, reviewDismissedText } from '@/lib/outcomes'

/**
 * `canopy dismiss` on one of a chore's open findings (DESIGN §19): `button` dismisses it, keeping it off the attention
 * list until the chore stops reporting it, or undoes that, listing it again; `notice` says what the last click did, or
 * why it was refused, and is nothing before one. The button sits in the finding's head line, the notice under it.
 */
export function useDismissFinding(chore: string, finding: string, dismissed: boolean) {
    const client = useQueryClient()
    return useDismiss({
        dismissed,
        act: async (undo) => dismissedText(await dismissFinding(chore, finding, undo)),
        refresh: () => refreshFindings(client, chore),
        labels: ['dismiss', 'undo'],
        titles: [
            'Keep it off the attention list until the chore stops reporting it',
            'List it on the attention list again',
        ],
        testId: finding,
    })
}

/**
 * `canopy dismiss review:ID N` on one of a review's findings (DESIGN §21): `button` dismisses it, so no worker or tick
 * acts on it, or undoes that; `notice` as for a chore's finding. Both undo as `canopy dismiss --undo` does. `words`, on
 * a review with a draft, names the button and says what a click did in the draft's terms, where the dismissal leaves
 * the finding out of the operator's review and taking it back puts it in again (DESIGN §34).
 */
export function useDismissReviewFinding(run: number, finding: number, dismissed: boolean, words?: DismissalWords) {
    const client = useQueryClient()
    return useDismiss({
        dismissed,
        act: async (undo) => (words?.said ?? reviewDismissedText)(await dismissReviewFinding(run, finding, undo)),
        refresh: () => refreshReview(client, run),
        labels: words?.labels ?? ['dismiss', 'undo'],
        titles: words?.titles ?? ['No worker or tick acts on it', 'Hand it to a resumed worker again'],
        testId: `finding-${finding}`,
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

interface Dismissal {
    dismissed: boolean
    act: (undo: boolean) => Promise<string>
    refresh: () => Promise<void>
    labels: [string, string]
    titles: [string, string]
    testId: string
}

function useDismiss({ dismissed, act, refresh, labels, titles, testId }: Dismissal) {
    const [said, setSaid] = useState<string | null>(null)
    const dismiss = useMutation({
        mutationFn: act,
        onSuccess: (text) => {
            setSaid(text)
            void refresh()
        },
    })
    const which = dismissed ? 1 : 0
    const button = (
        <Button
            variant="ghost"
            size="xs"
            // Negative margins keep the head line as tall as it is without the button.
            className="-my-1 text-muted-foreground"
            title={titles[which]}
            onClick={() => dismiss.mutate(dismissed)}
            disabled={dismiss.isPending}
            data-testid={`${dismissed ? 'undismiss' : 'dismiss'}-${testId}`}
        >
            {dismissed ? <Eye /> : <EyeOff />}
            {labels[which]}
        </Button>
    )
    const notice = <Notice error={dismiss.error}>{said}</Notice>
    return { button, notice }
}
