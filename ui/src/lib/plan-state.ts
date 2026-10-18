import type { TicketPlans } from '@/api/types'

/** Whether the newest plan waits on the operator: proposed, with no planner writing another and no changes asked. */
export function planWaits(plans: TicketPlans): boolean {
    return plans.newest?.plan.status === 'proposed' && plans.planning === null && plans.changes_asked === null
}

/**
 * Whether the newest plan can be approved as its file stands: one proposed, or one approved and changed since, while no
 * planner writes another.
 */
export function planApprovable(plans: TicketPlans): boolean {
    const newest = plans.newest
    if (newest === null || plans.planning !== null) {
        return false
    }
    return newest.plan.status === 'proposed' || (newest.plan.status === 'approved' && newest.changed_since_approval)
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
