import { Link } from '@tanstack/react-router'
import { Check } from 'lucide-react'

import { Leaf } from '@/components/leaf'

/**
 * What approving did, as the moment it is: the one time the operator lets an agent go ahead, on a ticket's plan or on
 * a feedback plan. It says so in the CLI's words on the accent's tint, as decided proposals do, rises in, and drops a
 * leaf, as a cleared attention item does, since approving clears the plan's item; then the way back to what else needs
 * the operator. Show it only once the approval is in the journal, so it never celebrates one that was refused; a new
 * `key` plays it again.
 */
export function ApprovedBand({ text }: { text: string }) {
    return (
        <div className="stagger">
            <div
                data-testid="plan-approved"
                className="relative flex flex-wrap items-center gap-x-3 gap-y-1 rounded-md bg-accent/14 px-2.5 py-1.5"
            >
                <Leaf className="-top-1 left-1" />
                <Check aria-hidden className="size-4 shrink-0 text-accent" />
                <output className="min-w-0 flex-1 text-sm text-accent">{text}</output>
                <Link to="/attention" className="text-xs font-medium text-accent underline-offset-4 hover:underline">
                    Back to Attention
                </Link>
            </div>
        </div>
    )
}
