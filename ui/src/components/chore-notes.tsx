import type { ChoreDetail } from '@/api/types'
import { Conversation, type Pending } from '@/components/conversation'
import { PanelHeader, Placeholder } from '@/components/panel'
import { ReplyForm } from '@/components/reply-form'
import { awaitsRun } from '@/lib/chores'

const UNREAD = 'No run of this chore has read it yet. Its next run does, as an instruction.'

/**
 * A chore's notes from the operator, the latest ten its next run reads, oldest first, and the form for another
 * (DESIGN §19). A note is about this week's findings: it stays until ten newer ones push it out, and a later one wins.
 */
export function ChoreNotes({ detail }: { detail: ChoreDetail }) {
    const { chore, notes } = detail
    const pending: Pending = {
        label: 'waiting for the next run',
        title: UNREAD,
        test: (note) => awaitsRun(note, chore),
    }
    return (
        <>
            <PanelHeader label="Your notes">
                <span className="readout text-xs text-muted-foreground">{notes.length}</span>
            </PanelHeader>
            {notes.length === 0 ? (
                <Placeholder className="min-h-20">no notes yet: its runs follow its prompt file alone</Placeholder>
            ) : (
                <Conversation messages={notes} pending={pending} />
            )}
            <ReplyForm key={chore.name} target={{ kind: 'chore', name: chore.name }} />
        </>
    )
}
