import type { FollowedEpicPlan, TicketMembership } from '@/api/types'
import { Age } from '@/components/age'
import { EpicLink } from '@/components/epic-link'
import { EpicPlanSha } from '@/components/epic-plan-sha'
import { Field } from '@/components/fields'
import { Tip } from '@/components/tip'

// What an entry set apart as dropped means, on hover: the epic's page is where the operator acts on it.
const DROPPED_HINT =
    'The approved plan no longer holds it. The ticket stays a member, of the entries left, until you register it ' +
    "again or remove it on the epic's page."

/**
 * A member ticket's epic, a field of its Work panel (DESIGN §43): `member of epic:1 · B2, B3`, the epic opening its
 * page, or `of no entry` for a member its breakdown did not foresee. Entries a later approved plan dropped follow,
 * muted, as the epic's page sets them apart. A ticket of no epic has no such field.
 */
export function MembershipField({ membership }: { membership: TicketMembership | null }) {
    if (membership === null) {
        return null
    }
    const { entries, dropped } = membership
    return (
        <Field label="member of" mono data-testid="ticket-membership">
            <EpicLink id={membership.epic_id} />
            <span className="text-muted-foreground"> · </span>
            {entries.length > 0 ? (
                <span className="readout">{entries.join(', ')}</span>
            ) : (
                <span className="text-muted-foreground">of no entry</span>
            )}
            {dropped.length > 0 && (
                <Tip fact={DROPPED_HINT}>
                    <span className="text-muted-foreground">
                        {' · '}
                        <span className="readout">{dropped.join(', ')}</span> dropped
                    </span>
                </Tip>
            )}
        </Field>
    )
}

/**
 * The epic plan a member ticket's plan was written against, a line under its plan page's description: the epic,
 * opening its page, the plan's hash as the operator approved it, and when they did. A newer plan approved since is
 * said as a fact, with when; what it changed for this plan is the operator's to read on the epic's page.
 */
export function FollowedEpicPlanLine({ followed }: { followed: FollowedEpicPlan | null }) {
    if (followed === null) {
        return null
    }
    return (
        <p className="mt-1 text-xs text-balance text-muted-foreground" data-testid="plan-epic">
            <span className="mr-2 panel-label">follows</span>
            <EpicLink id={followed.epic_id} />
            &rsquo;s plan
            {followed.sha256 !== null && (
                <>
                    {' '}
                    <EpicPlanSha sha256={followed.sha256} copy={false} />
                </>
            )}
            {followed.approved_at !== null && (
                <>
                    , approved <Age at={followed.approved_at} variant="ago" />
                </>
            )}
            .
            {followed.newer_approved_at !== null && (
                <span data-testid="plan-epic-newer">
                    {' '}
                    A newer epic plan was approved <Age at={followed.newer_approved_at} variant="ago" />.
                </span>
            )}
        </p>
    )
}
