import type { ReviewDraft } from '@/api/types'
import { Chip } from '@/components/status'
import { Tip } from '@/components/tip'
import { REVIEW_DRAFT_MEANS, REVIEW_DRAFT_TONE, REVIEW_DRAFT_WORD } from '@/lib/review-drafts'
import { cn } from '@/lib/utils'

/**
 * Where the operator's review of a PR the loop does not own stands, as a list's row or a field says it (DESIGN §34):
 * `draft` while it waits on them, else `publishing`, `unconfirmed`, `staged`, or `published`, in `REVIEW_DRAFT_TONE`,
 * so a staged or unconfirmed one, which waits on them on GitHub, stands out and the rest stay quiet. Its hover gives
 * the journal's word and what it means.
 */
export function ReviewDraftChip({ status, className }: { status: ReviewDraft['status']; className?: string }) {
    return (
        <Tip fact={`${status}: ${REVIEW_DRAFT_MEANS[status]}`}>
            <span className={cn('inline-flex shrink-0', className)}>
                <Chip tone={REVIEW_DRAFT_TONE[status]}>{REVIEW_DRAFT_WORD[status]}</Chip>
            </span>
        </Tip>
    )
}
