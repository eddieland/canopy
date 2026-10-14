import type { ChoreDetail } from '@/api/types'
import { Conversation } from '@/components/conversation'
import type { Pending } from '@/components/conversation'
import { OrderToggle } from '@/components/order-toggle'
import { Empty, PanelHeader } from '@/components/panel'
import { ReplyForm } from '@/components/reply-form'
import { awaitsRun } from '@/lib/chores'
import { ordered, useListOrder } from '@/lib/list-order'

const UNREAD = 'No run of this chore has read it yet. Its next run does, as an instruction.'

/**
 * A chore's notes from the operator, the latest ten its next run reads, oldest first, and the form for another
 * (DESIGN §19). A note is about this week's findings: it stays until ten newer ones push it out, and a later one wins.
 */
export function ChoreNotes({ detail }: { detail: ChoreDetail }) {
    const { chore, notes } = detail
    const order = useListOrder('notes')
    const pending: Pending = {
        label: 'waiting for the next run',
        title: UNREAD,
        test: (note) => awaitsRun(note, chore),
    }
    return (
        <>
            <PanelHeader label="Notes">
                <span className="flex items-center gap-2">
                    {notes.length > 1 && <OrderToggle list="notes" />}
                    <span className="readout text-xs text-muted-foreground">{notes.length}</span>
                </span>
            </PanelHeader>
            {notes.length === 0 ? (
                <Empty>no notes yet: its runs follow its prompt file alone</Empty>
            ) : (
                <Conversation messages={ordered('notes', order, notes)} pending={pending} />
            )}
            <ReplyForm key={chore.name} target={{ kind: 'chore', name: chore.name }} />
        </>
    )
}
