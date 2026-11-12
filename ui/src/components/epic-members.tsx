import { useQueryClient } from '@tanstack/react-query'
import { Plus, UserMinus, X } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import type { SubmitEvent } from 'react'

import { addEpicMember, removeEpicMember } from '@/api/mutations'
import { keys } from '@/api/queries'
import type { EpicEntry } from '@/api/types'
import { Input } from '@/components/input'
import { Notice } from '@/components/notice'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { usePoint } from '@/hooks/use-outline-lights'
import { epicMemberAddedText, epicMemberRemovedText } from '@/lib/outcomes'
import { epicRef } from '@/lib/refs'
import { cn } from '@/lib/utils'

/**
 * The form that makes a ticket a member, `canopy epic add`: its key, and the entries of the approved breakdown it
 * fulfils, `picked` checked at first, or none for a ticket the breakdown did not foresee. It says what adding does
 * and does not: it authorizes no work, a member is worked once labeled or started, and registering a member again
 * replaces its entries. Done, it hands up what the CLI would say and closes; refused, it stays open, naming the guard.
 * Escape in its field, or Cancel, closes it. `members` are the epic's members' keys, so the button says when it
 * registers one again.
 */
export function MemberForm({
    epic,
    entries,
    why,
    picked,
    members,
    onDone,
    onCancel,
    className,
}: {
    epic: number
    entries: readonly EpicEntry[]
    why: string | null
    picked: readonly string[]
    members: readonly string[]
    onDone: (said: string) => void
    onCancel: () => void
    className?: string
}) {
    const field = useRef<HTMLInputElement>(null)
    const [key, setKey] = useState('')
    const [checked, setChecked] = useState<readonly string[]>(picked)
    const { busy, failure, act } = useWrite(epic, onDone)
    // The key is typed next: the form opens for it.
    useEffect(() => {
        field.current?.focus()
    }, [])
    const typed = key.trim()
    const again = members.includes(typed)
    const named = entries.map((entry) => entry.id).filter((id) => checked.includes(id))
    const flags = named.length === 0 ? '--no-entry' : named.map((id) => `--entry ${id}`).join(' ')
    const command = `canopy epic add ${epicRef(epic)} ${typed === '' ? 'KEY' : typed} ${flags}`

    function submit(event: SubmitEvent<HTMLFormElement>) {
        event.preventDefault()
        if (typed === '' || busy) {
            return
        }
        void act(async () => epicMemberAddedText(epic, await addEpicMember(epic, typed, named)))
    }

    return (
        <form
            aria-label={picked.length === 1 ? `Register a ticket against ${picked[0] ?? ''}` : 'Add a ticket'}
            className={cn('flex flex-col gap-2', className)}
            onSubmit={submit}
        >
            <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
                <Input
                    ref={field}
                    aria-label="Ticket key"
                    placeholder="Ticket key"
                    value={key}
                    onChange={(event) => setKey(event.target.value)}
                    onKeyDown={(event) => {
                        if (event.key === 'Escape') {
                            onCancel()
                        }
                    }}
                    autoComplete="off"
                    spellCheck={false}
                    className="w-36 font-mono"
                />
                {entries.length > 0 && (
                    <fieldset className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
                        <legend className="sr-only">Entries it fulfils</legend>
                        <span aria-hidden className="panel-label">
                            fulfils
                        </span>
                        {entries.map((entry) => (
                            <EntryChoice
                                key={entry.id}
                                entry={entry}
                                checked={checked.includes(entry.id)}
                                onChange={(on) =>
                                    setChecked((was) => (on ? [...was, entry.id] : was.filter((id) => id !== entry.id)))
                                }
                            />
                        ))}
                    </fieldset>
                )}
                <span className="flex items-center gap-2">
                    <Button type="submit" disabled={typed === '' || busy} title={command}>
                        <Plus />
                        {again ? 'Register again' : named.length > 0 ? 'Add and register' : 'Add'}
                    </Button>
                    <Button type="button" variant="ghost" onClick={onCancel} disabled={busy}>
                        Cancel
                    </Button>
                </span>
            </div>
            <p className="text-xs text-muted-foreground">
                {why === null ? null : `${why} `}
                Adding a ticket authorizes no work: a member is worked once you label it or start it. Registering a
                member again replaces its entries
                {entries.length > 0 ? '; check none for a ticket the breakdown did not foresee.' : '.'}
            </p>
            <Notice error={failure} />
        </form>
    )
}

/**
 * A member's Remove: a ghost icon, muted until hovered, then in the failure color, as a verb that ends something is.
 * It asks first (`RemoveQuestion`) rather than removing. `asking` marks it while its question is open.
 */
export function RemoveButton({ member, asking, onAsk }: { member: string; asking: boolean; onAsk: () => void }) {
    return (
        <Button
            variant="ghost"
            size="icon-xs"
            aria-label={`Remove ${member}`}
            aria-expanded={asking}
            title={`Remove ${member} from the epic`}
            onClick={onAsk}
            className={cn(
                'text-muted-foreground hover:text-status-failed',
                // Shown while its member's line is hovered or holds the focus, asked, or on a touch screen.
                'opacity-0 group-focus-within/member:opacity-100 group-hover/member:opacity-100',
                'pointer-coarse:opacity-100',
                asking && 'text-status-failed opacity-100',
            )}
        >
            <X />
        </Button>
    )
}

/**
 * The question before a member is removed, `canopy epic remove`: Remove KEY from epic:N, in the failure color, or
 * Keep it, and what removing leaves as it was. Done, it hands up what the CLI would say; refused, it stays, naming the
 * guard.
 */
export function RemoveQuestion({
    epic,
    member,
    onDone,
    onCancel,
    className,
}: {
    epic: number
    member: string
    onDone: (said: string) => void
    onCancel: () => void
    className?: string
}) {
    const { busy, failure, act } = useWrite(epic, onDone)
    return (
        <div className={cn('flex flex-col gap-1.5', className)}>
            <div className="flex flex-wrap items-center gap-2">
                <Button
                    variant="destructive"
                    size="xs"
                    onClick={() => {
                        void act(async () => epicMemberRemovedText(epic, await removeEpicMember(epic, member)))
                    }}
                    disabled={busy}
                    title={`canopy epic remove ${epicRef(epic)} ${member}`}
                >
                    <UserMinus />
                    Remove {member} from {epicRef(epic)}
                </Button>
                <Button variant="ghost" size="xs" onClick={onCancel} disabled={busy}>
                    Keep it
                </Button>
                <span className="text-xs text-muted-foreground">
                    It stops being a member; the ticket and its work stay as they are.
                </span>
            </div>
            <Notice error={failure} />
        </div>
    )
}

/**
 * An entry to check in the form, its id and title, lighting its row on the board while pointed at, as an id does.
 */
function EntryChoice({
    entry,
    checked,
    onChange,
}: {
    entry: EpicEntry
    checked: boolean
    onChange: (on: boolean) => void
}) {
    const pointAt = usePoint()
    return (
        <label
            className="inline-flex min-w-0 items-center gap-1.5 text-xs"
            onPointerEnter={() => {
                pointAt({ by: 'hover', id: entry.id, on: true })
            }}
            onPointerLeave={() => {
                pointAt({ by: 'hover', id: entry.id, on: false })
            }}
        >
            <Checkbox
                checked={checked}
                onCheckedChange={(on) => onChange(on === true)}
                onFocus={() => {
                    pointAt({ by: 'focus', id: entry.id, on: true })
                }}
                onBlur={() => {
                    pointAt({ by: 'focus', id: entry.id, on: false })
                }}
            />
            <span className="readout">{entry.id}</span>
            <span className="max-w-48 truncate text-muted-foreground">{entry.title}</span>
        </label>
    )
}

/**
 * A membership write's state: busy while it runs, what refused it, and `act`, which runs it, hands up what it said,
 * and reads the epic and the list again once it ends, done or refused, since no stream event carries an epic.
 */
function useWrite(epic: number, onDone: (said: string) => void) {
    const client = useQueryClient()
    const [busy, setBusy] = useState(false)
    const [failure, setFailure] = useState<unknown>(null)

    async function act(work: () => Promise<string>): Promise<void> {
        setFailure(null)
        setBusy(true)
        let said: string | null = null
        try {
            said = await work()
        } catch (error: unknown) {
            setFailure(error)
        }
        setBusy(false)
        void client.invalidateQueries({ queryKey: keys.epic(epic) })
        void client.invalidateQueries({ queryKey: keys.epics })
        if (said !== null) {
            onDone(said)
        }
    }

    return { busy, failure, act }
}
