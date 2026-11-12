import type { EpicPlans, PlanFile, TicketPlans } from '@/api/types'
import { planDecisions } from '@/lib/plan-decisions'
import type { PlanDecision } from '@/lib/plan-decisions'

/** Whether the newest plan waits on the operator: proposed, with no planner writing another and no changes asked. */
export function planWaits(plans: TicketPlans): boolean {
    return plans.newest?.plan.status === 'proposed' && plans.planning === null && plans.changes_asked === null
}

/**
 * Whether the newest plan can be approved as its file stands: one proposed, or one approved whose file or ticket
 * changed since, while no planner writes another.
 */
export function planApprovable(plans: TicketPlans): boolean {
    const newest = plans.newest
    if (newest === null || plans.planning !== null) {
        return false
    }
    return newest.plan.status === 'proposed' || (newest.plan.status === 'approved' && approvedChanged(newest))
}

/**
 * The decisions a ticket's newest plan leaves open to the operator (`planDecisions`): those of a plan proposed, as its
 * file reads now, while no planner writes another. None once it is approved or replaced, or while its file does not
 * read.
 */
export function openDecisions(plans: TicketPlans): PlanDecision[] {
    const newest = plans.newest
    if (newest?.plan.status !== 'proposed' || plans.planning !== null) {
        return []
    }
    return planDecisions(newest.text ?? '')
}

/** The decisions an epic's newest plan leaves open to the operator, as `openDecisions` finds a ticket's. */
export function epicOpenDecisions(plans: EpicPlans): PlanDecision[] {
    const newest = plans.plans.at(-1)
    if (newest?.plan.status !== 'proposed' || plans.planning !== null) {
        return []
    }
    return planDecisions(newest.text ?? '')
}

/**
 * What a plan's Approve reads, so its own words say what it takes: `Approve with notes` when it carries any to the
 * implement, an answer to a decision among them; `Approve as planned` when it carries none and the plan has open
 * decisions, each then taken as the planner chose; else `Approve`. With `saves`, it leads with the save an edit not yet
 * saved needs first.
 */
export function approveLabel({
    saves = false,
    noted = false,
    planned = false,
}: {
    /** Whether the plan has edits not yet saved, which approving saves first. */
    saves?: boolean
    /** Whether the approval carries notes to the implement. */
    noted?: boolean
    /** Whether the plan has open decisions, which an approval with no notes takes as the planner chose. */
    planned?: boolean
}): string {
    const approve = saves ? 'Save and approve' : 'Approve'
    if (noted) {
        return `${approve} with notes`
    }
    return planned ? `${approve} as planned` : approve
}

/** Whether an approved plan's file, or its ticket's title or description, changed since it was approved. */
export function approvedChanged(newest: PlanFile): boolean {
    return newest.changed_since_approval || newest.ticket_changed.length > 0
}

/**
 * What of an approved plan's ticket changed since its approval, in a sentence, or null when nothing did: the harness's
 * `ticket_changed` warning, which holds nothing up. Approving again says the plan still fits.
 */
export function ticketChangedNote(newest: PlanFile): string | null {
    if (newest.ticket_changed.length === 0) {
        return null
    }
    const what = newest.ticket_changed.join(' and ')
    return `Its ticket’s ${what} changed since you approved it: approve it again if it still fits.`
}

/**
 * Why the ticket needs a plan or not, in a sentence for a hover: the operator's own word, its epic's plan, which may
 * mark it trivial, or `policy.plan`.
 */
export function planNeededWhy(plans: TicketPlans): string {
    switch (plans.setting) {
        case 'plan': {
            return 'You asked for a plan (canopy plan): its implement waits on one you approve.'
        }
        case 'skip': {
            return 'You waived its plan (canopy plan --skip): its implement goes ahead without one.'
        }
        case null: {
            if (plans.policy === 'approve' && plans.trivial !== null) {
                const why = `Its epic's plan marks it trivial (${plans.trivial})`
                return `${why}: your approval of that plan stands for its own.`
            }
            return plans.policy === 'approve'
                ? 'policy.plan is approve: every implement waits on a plan you approve.'
                : 'policy.plan is off: no ticket waits on a plan unless you ask for one.'
        }
    }
}
