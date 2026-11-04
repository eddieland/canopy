import type { PlanFile, TicketPlans } from '@/api/types'

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

/** Why the ticket needs a plan or not, in a sentence for a hover: the operator's own word, or `policy.plan`. */
export function planNeededWhy(plans: TicketPlans): string {
    switch (plans.setting) {
        case 'plan': {
            return 'You asked for a plan (canopy plan): its implement waits on one you approve.'
        }
        case 'skip': {
            return 'You waived its plan (canopy plan --skip): its implement goes ahead without one.'
        }
        case null: {
            return plans.policy === 'approve'
                ? 'policy.plan is approve: every implement waits on a plan you approve.'
                : 'policy.plan is off: no ticket waits on a plan unless you ask for one.'
        }
    }
}
