import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { CodeXml, LampDesk, Trash2, X } from 'lucide-react'
import { useState } from 'react'

import { ApiError } from '@/api/client'
import { closeDesk, openDesk, refreshDesk } from '@/api/mutations'
import { tickQuery } from '@/api/queries'
import type { OpenDesk, TicketDesk as TicketDeskData } from '@/api/types'
import { Copyable, CopyablePath } from '@/components/copy-button'
import { ForgetForm } from '@/components/forget-form'
import { Notice } from '@/components/notice'
import { RepoFilter } from '@/components/repo-picker'
import { Button } from '@/components/ui/button'
import { deskClosedText, deskOpenedText } from '@/lib/outcomes'
import { cn } from '@/lib/utils'

/**
 * The operator's desk on a ticket (DESIGN §18), at the foot of its Work panel: its branch checked out for them in a
 * slot of each repository's pool, as `canopy desk KEY` does, to edit in VS Code. Closed, it is Open desk, after a
 * repository picker when the branch is in more than one; open, its lamp is lit, and it lists each repository's slot,
 * a link that opens the desk's workspace file in VS Code, the `code` line that does the same from a terminal, and
 * Close desk. A close refused for work origin lacks says what, and offers to discard it, which cannot be undone, so it
 * asks for the ticket's key typed out, as Forget does. Either action waits for a running tick to end, and says so
 * meanwhile. With no branch yet, and no desk, it is not there at all.
 */
export function TicketDesk({
    ticketKey,
    desk,
    className,
}: {
    /** The ticket the desk is of. */
    ticketKey: string
    /** What a desk would cover, and the desk while open. */
    desk: TicketDeskData
    /** Classes for the section, such as its border. */
    className?: string
}) {
    const client = useQueryClient()
    const [said, setSaid] = useState<string | null>(null)
    const [chosen, setChosen] = useState<string[]>([])
    const [discarding, setDiscarding] = useState(false)
    const ticking = useQuery(tickQuery).data?.tick?.status === 'running'
    const open = useMutation({
        mutationFn: () => openDesk(ticketKey, chosen),
        onMutate: () => setSaid(null),
        onSuccess: (opened) => {
            setSaid(deskOpenedText(ticketKey, opened))
            setChosen([])
            void refreshDesk(client, ticketKey)
        },
    })
    const close = useMutation({
        mutationFn: (confirm?: string) => closeDesk(ticketKey, confirm),
        onMutate: () => setSaid(null),
        onSuccess: (closed) => {
            setSaid(deskClosedText(ticketKey, closed))
            setDiscarding(false)
            void refreshDesk(client, ticketKey)
        },
    })
    if (desk.open === null && desk.repos.length === 0) {
        return null
    }
    const pending = open.isPending || close.isPending
    // A close refused for work origin lacks is the one refusal a click here can answer: discard it.
    const unpushed = close.error instanceof ApiError && close.error.guard === 'unpushed'
    return (
        <section className={cn('flex flex-col gap-2 p-3', className)} aria-label="Desk" data-testid="ticket-desk">
            <div className="flex min-h-6 flex-wrap items-center gap-x-2 gap-y-1">
                <h3 className="panel-label">desk</h3>
                {desk.open !== null && (
                    <span className="inline-flex min-w-0 items-center gap-1 font-mono text-xs text-muted-foreground">
                        {/* Lit while open: the accent marks what is live. */}
                        <LampDesk className="size-3 shrink-0 text-accent" aria-hidden />
                        <span className="text-foreground">open</span>
                        <span aria-hidden>·</span>
                        <span className="min-w-0 truncate" title={desk.open.path}>
                            {desk.open.path}
                        </span>
                    </span>
                )}
                <span className="ml-auto flex items-center gap-2">
                    {desk.open === null && desk.repos.length > 1 && (
                        <RepoFilter
                            repos={desk.repos}
                            chosen={chosen}
                            onChoose={setChosen}
                            label="Repositories at the desk"
                        />
                    )}
                    {desk.open === null ? (
                        <Button variant="outline" size="xs" disabled={pending} onClick={() => open.mutate()}>
                            <LampDesk />
                            Open desk
                        </Button>
                    ) : (
                        !discarding && (
                            <Button variant="outline" size="xs" disabled={pending} onClick={() => close.mutate()}>
                                <X />
                                Close desk
                            </Button>
                        )
                    )}
                </span>
            </div>
            {desk.open === null ? (
                <p className="text-xs text-muted-foreground">
                    None open. Open one to check its branch out for yourself, a slot per repository, and edit it in VS
                    Code; no tick takes it back.
                </p>
            ) : (
                <OpenDeskBody desk={desk.open} />
            )}
            {unpushed && !discarding && (
                <Button
                    variant="ghost"
                    size="xs"
                    className="self-start text-status-failed hover:text-status-failed"
                    onClick={() => setDiscarding(true)}
                    disabled={pending}
                >
                    <Trash2 />
                    Discard it and close
                </Button>
            )}
            {discarding && (
                <ForgetForm
                    confirm={ticketKey}
                    name="Discard the desk's work"
                    action="Discard and close"
                    icon={Trash2}
                    pending={pending}
                    onForget={(typed) => close.mutate(typed)}
                    onCancel={() => setDiscarding(false)}
                >
                    canopy throws away the uncommitted changes and the commits origin lacks in every slot of the desk,
                    returns the slots to their pools, and deletes the local branch. What is on origin stays. This cannot
                    be undone.
                </ForgetForm>
            )}
            <Notice error={open.error ?? close.error}>{pending ? waitText(ticking, open.isPending) : said}</Notice>
        </section>
    )
}

/**
 * An open desk: each repository's slot, on the branch the Work panel names above, then the two ways to open it in VS
 * Code.
 */
function OpenDeskBody({ desk }: { desk: OpenDesk }) {
    return (
        <>
            <dl className="grid grid-cols-[max-content_minmax(0,1fr)] gap-x-3 gap-y-1 font-mono text-xs">
                {desk.slots.map((slot) => (
                    <div key={slot.repo} className="group/copy col-span-full grid grid-cols-subgrid items-baseline">
                        <dt className="text-foreground">{slot.repo}</dt>
                        <dd className="min-w-0 text-muted-foreground">
                            <CopyablePath path={slot.path} label={`${slot.repo}'s slot`} reveal />
                        </dd>
                    </div>
                ))}
            </dl>
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                {/* A link to the editor's own URL handler: the browser hands it to VS Code, and no page opens. */}
                <Button asChild variant="outline">
                    <a href={desk.editor_url} title={`Open ${desk.workspace_file} in VS Code`}>
                        <CodeXml />
                        Open in VS Code
                    </a>
                </Button>
                {/* Its own span, so a screenshot can hide the mock's temporary directory in it. */}
                <span className="min-w-0" data-testid="desk-command">
                    <Copyable
                        text={desk.open_command}
                        label="command"
                        className="font-mono text-xs text-muted-foreground"
                    />
                </span>
            </div>
        </>
    )
}

/** What an open or a close in flight is doing: waiting for the tick that holds the pools, or working. */
function waitText(ticking: boolean, opening: boolean): string {
    if (ticking) {
        return `A tick is running; the ${opening ? 'open' : 'close'} starts when it ends.`
    }
    return opening ? 'Opening the desk: a slot per repository, on its branch.' : 'Closing the desk.'
}
