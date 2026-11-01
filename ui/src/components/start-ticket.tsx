import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from '@tanstack/react-router'
import { Play } from 'lucide-react'
import { useId, useState } from 'react'
import type { SubmitEvent } from 'react'

import { refreshTicket, startTicket } from '@/api/mutations'
import { configQuery } from '@/api/queries'
import { Disclosure } from '@/components/disclosure'
import { Input } from '@/components/input'
import { Notice } from '@/components/notice'
import { StartChoices } from '@/components/start-choices'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Collapsible, CollapsibleContent } from '@/components/ui/collapsible'
import { NO_PICKS, pickCount, planAsked, startRequest } from '@/lib/start-picks'
import type { StartPicks } from '@/lib/start-picks'

/**
 * Starts a ticket privately by its key (DESIGN §22), then opens its page. The tickets page and the Start a ticket
 * dialog (`TicketDialog`), which `T` opens from anywhere, both render it, so the two cannot drift. Beside the button,
 * `Plan it first`, checked as `policy.plan` is set in Settings until the operator changes it: checked against an `off`
 * policy it asks for a plan, as `canopy start KEY --plan` does, and unchecked against `approve` it waives one, as
 * `canopy plan KEY --skip` does. Under the key, a disclosure opens the persona and the model each of the ticket's
 * agents takes (`StartChoices`), set as the ticket's overrides; closed, it says how many are picked, so none is sent
 * unseen. All of it goes with the start or not at all.
 */
export function StartTicket({
    focus = false,
    onStarted,
}: {
    /** Whether the key field takes the focus as the form mounts: the dialog's, which opens on a key to type in. */
    focus?: boolean
    /** Hears the ticket start, as the form opens its page. */
    onStarted?: () => void
}) {
    const client = useQueryClient()
    const navigate = useNavigate()
    const id = useId()
    const [open, setOpen] = useState(false)
    const [picks, setPicks] = useState<StartPicks>(NO_PICKS)
    // Whether the operator checked or unchecked `Plan it first`; null while it follows `policy.plan`.
    const [planPick, setPlanPick] = useState<boolean | null>(null)
    const { data: config } = useQuery(configQuery)
    const policy = config?.keys.find((key) => key.name === 'policy.plan')?.value === 'approve'
    const plan = planPick ?? policy
    const mutation = useMutation({
        mutationFn: ({ key, chosen }: { key: string; chosen: StartPicks }) =>
            startTicket(key, { ...startRequest(chosen), plan: planAsked(plan, policy) }),
        onSuccess: (_started, { key }) => {
            void refreshTicket(client, key)
            onStarted?.()
            void navigate({ to: '/tickets/$key', params: { key } })
        },
    })

    function submit(event: SubmitEvent<HTMLFormElement>) {
        event.preventDefault()
        const key = new FormData(event.currentTarget).get('key')
        if (typeof key === 'string' && key.trim()) {
            mutation.mutate({ key: key.trim(), chosen: picks })
        }
    }

    const picked = pickCount(picks)
    return (
        <form onSubmit={submit} aria-label="Start a ticket" aria-keyshortcuts="T" className="flex flex-col gap-2 p-3">
            <div className="flex items-center gap-2">
                <Input
                    name="key"
                    placeholder="PROJ-123"
                    aria-label="Ticket key"
                    // oxlint-disable-next-line jsx-a11y/no-autofocus -- the dialog opens on a key, to type in.
                    autoFocus={focus}
                    className="max-w-56 min-w-0 font-mono"
                />
                <Button type="submit" variant="outline" disabled={mutation.isPending}>
                    <Play />
                    Start privately
                </Button>
                {/* Kept whole: when the row is tight the key field gives, never the label's words. */}
                <span className="flex shrink-0 items-center gap-1.5 whitespace-nowrap">
                    <Checkbox
                        id={`${id}-plan`}
                        checked={plan}
                        disabled={mutation.isPending}
                        onCheckedChange={(checked) => setPlanPick(checked === true)}
                    />
                    <label htmlFor={`${id}-plan`} className="text-xs" title={planTitle(plan, policy)}>
                        Plan it first
                    </label>
                    {planPick === null && policy && <span className="text-xs text-muted-foreground">policy.plan</span>}
                </span>
            </div>
            <Collapsible open={open} onOpenChange={setOpen} className="flex flex-col gap-1.5">
                <span className="flex items-baseline gap-2">
                    <Disclosure open={open} what="persona and model overrides" className="-ml-2 self-start" />
                    {!open && picked > 0 && (
                        <span className="text-xs text-muted-foreground" data-testid="start-picked">
                            {picked} picked
                        </span>
                    )}
                </span>
                <CollapsibleContent>
                    <StartChoices picks={picks} disabled={mutation.isPending} onChange={setPicks} />
                </CollapsibleContent>
            </Collapsible>
            <Notice error={mutation.error}>
                No queue label needed. Its conversation stays in canopy: nothing reaches the ticket.
            </Notice>
        </form>
    )
}

/** What `Plan it first` stands for, on hover: the command it is, or that `policy.plan` already does it. */
function planTitle(plan: boolean, policy: boolean): string {
    if (plan === policy) {
        return policy ? 'policy.plan is approve: its implement waits on a plan you approve' : 'canopy start KEY --plan'
    }
    return plan ? 'canopy start KEY --plan' : 'canopy plan KEY --skip: its implement waits on no plan'
}
