import { useQuery } from '@tanstack/react-query'
import { useNavigate, useParams } from '@tanstack/react-router'
import { Search } from 'lucide-react'
import { useEffect, useState } from 'react'

import { ticketsQuery } from '@/api/queries'
import type { TicketSummary } from '@/api/types'
import { RunDot } from '@/components/status'
import { Command, CommandGroup, CommandInput, CommandItem, CommandList } from '@/components/ui/command'
import { Dialog, DialogContent, DialogDescription, DialogTitle } from '@/components/ui/dialog'
import { Kbd } from '@/components/ui/kbd'
import { phaseLabel } from '@/lib/phase'
import { keepKnown, useRecentTickets } from '@/lib/recent-tickets'
import type { RecentTicket } from '@/lib/recent-tickets'
import { runRef } from '@/lib/refs'
import { RUN_TEXT } from '@/lib/run-state'
import { searchQueryOf } from '@/lib/search'
import { isApple } from '@/lib/send-key'
import { isPressed, keysLabel } from '@/lib/shortcut'
import { keyOrTitleHolds, TICKET_QUERY_MAX } from '@/lib/ticket-filter'
import { age, useNow } from '@/lib/time'
import { cn } from '@/lib/utils'

/** The keys that open and close the palette, as `src/lib/shortcut.ts` writes them: ⌘K on an Apple keyboard, Ctrl+K. */
export const JUMP_KEYS = 'Mod-k'

/** How many recently viewed tickets the palette lists. */
export const RECENT_SHOWN = 8
/** How many other tickets a query lists before `+N more`. */
export const MATCHES_SHOWN = 20

const APPLE = isApple(navigator.userAgent)

/**
 * The jump palette (ui/DESIGN.md, The jump palette): ⌘K (Ctrl+K elsewhere) from anywhere, a text field included,
 * opens a field over the tickets the operator viewed last in this browser, newest first, without the one on screen, so
 * ⌘K Enter goes back to the ticket before it. Typing narrows them by key or title, and lists the other tickets that
 * match under them; when none does, it offers the journal's search. Enter opens the one the keys are on. The same
 * keys close it, as do Escape and a click outside.
 */
export function JumpPalette({
    open,
    onOpenChange,
}: {
    /** Whether it is open. */
    open: boolean
    /** Hears it opened, by its keys or `JumpButton`, or closed. */
    onOpenChange: (open: boolean) => void
}) {
    useEffect(() => {
        function onKey(event: KeyboardEvent) {
            if (isPressed(JUMP_KEYS, event, APPLE)) {
                event.preventDefault()
                onOpenChange(!open)
            }
        }
        globalThis.addEventListener('keydown', onKey)
        return () => {
            globalThis.removeEventListener('keydown', onKey)
        }
    }, [open, onOpenChange])
    return (
        <Dialog open={open} onOpenChange={onOpenChange}>
            <DialogContent data-testid="jump-palette">
                <DialogTitle className="sr-only">Jump to a ticket</DialogTitle>
                <DialogDescription className="sr-only">
                    The tickets you viewed last, then every ticket whose key or title holds what you type
                </DialogDescription>
                <Jump
                    onJump={() => {
                        onOpenChange(false)
                    }}
                />
            </DialogContent>
        </Dialog>
    )
}

/** The keycap that opens the palette, at the end of the rail's search box while it is empty. */
export function JumpButton({ onOpen }: { onOpen: () => void }) {
    return (
        <button
            type="button"
            aria-label="Jump to a ticket"
            aria-keyshortcuts={APPLE ? 'Meta+K' : 'Control+K'}
            title="Jump to a ticket you viewed"
            onClick={onOpen}
            className="rounded-sm outline-none focus-visible:ring-3 focus-visible:ring-ring/50"
        >
            <Kbd className="hover:text-foreground">{keysLabel(JUMP_KEYS, APPLE)}</Kbd>
        </button>
    )
}

/** The field and its list. Mounted only while the palette is open, so each opening starts with an empty field. */
function Jump({ onJump }: { onJump: () => void }) {
    const navigate = useNavigate()
    const here = useParams({ strict: false }).key
    const [text, setText] = useState('')
    const recent = useRecentTickets()
    const tickets = useQuery(ticketsQuery).data
    // A ticket viewed and forgotten since is no longer the journal's: it leaves the list, and the store with it.
    useEffect(() => {
        if (tickets !== undefined) {
            keepKnown(new Set(tickets.map((t) => t.key)))
        }
    }, [tickets])

    const byKey = new Map(tickets?.map((t) => [t.key, t]))
    const query = text.trim() === '' ? undefined : text
    const shownRecent = recent
        .filter((t) => t.key !== here && (tickets === undefined || byKey.has(t.key)))
        .filter((t) => keyOrTitleHolds({ key: t.key, title: byKey.get(t.key)?.title ?? t.title }, query))
        .slice(0, RECENT_SHOWN)
    const listed = new Set(shownRecent.map((t) => t.key))
    // Nothing typed lists the recent tickets alone, not every ticket.
    const matches = (query === undefined ? [] : (tickets ?? []))
        .filter((t) => !listed.has(t.key) && keyOrTitleHolds(t, query))
        .toSorted((a, b) => b.active_at.localeCompare(a.active_at))
    const search = searchQueryOf(text)

    function go(key: string) {
        onJump()
        void navigate({ to: '/tickets/$key', params: { key } })
    }

    function searchJournal(q: string) {
        onJump()
        void navigate({ to: '/search', search: { q } })
    }

    return (
        <Command label="Jump to a ticket" shouldFilter={false} className="rounded-md">
            <CommandInput
                placeholder="Jump to a ticket"
                value={text}
                onValueChange={setText}
                maxLength={TICKET_QUERY_MAX}
                className="h-11 text-sm"
            />
            <CommandList label="Tickets" className="max-h-[min(28rem,60dvh)] p-1.5">
                {query === undefined && shownRecent.length === 0 && (
                    <p className="px-2 py-6 text-center text-xs text-muted-foreground">
                        Tickets you open show up here. Type to find any ticket.
                    </p>
                )}
                {shownRecent.length > 0 && (
                    <CommandGroup heading="Recent">
                        {shownRecent.map((t) => (
                            <JumpItem
                                key={t.key}
                                value={`recent ${t.key}`}
                                ticketKey={t.key}
                                title={byKey.get(t.key)?.title ?? t.title}
                                summary={byKey.get(t.key)}
                                viewed={t}
                                onSelect={() => go(t.key)}
                            />
                        ))}
                    </CommandGroup>
                )}
                {matches.length > 0 && (
                    <CommandGroup heading="Tickets" className={cn(shownRecent.length > 0 && 'mt-1.5 border-t pt-1.5')}>
                        {matches.slice(0, MATCHES_SHOWN).map((t) => (
                            <JumpItem
                                key={t.key}
                                value={`ticket ${t.key}`}
                                ticketKey={t.key}
                                title={t.title}
                                summary={t}
                                onSelect={() => go(t.key)}
                            />
                        ))}
                        {matches.length > MATCHES_SHOWN && (
                            <CommandItem
                                value="more"
                                onSelect={() => {
                                    onJump()
                                    void navigate({ to: '/tickets', search: { q: query } })
                                }}
                                className="text-xs text-muted-foreground"
                            >
                                <span className="readout">+{matches.length - MATCHES_SHOWN}</span> more on the tickets
                                page
                            </CommandItem>
                        )}
                    </CommandGroup>
                )}
                {query !== undefined && shownRecent.length === 0 && matches.length === 0 && (
                    <NoMatch text={text} onSearch={search === undefined ? undefined : () => searchJournal(search)} />
                )}
            </CommandList>
            <Keys />
        </Command>
    )
}

/**
 * A ticket in the list: its key, its title, then where it stands now, and for one viewed, how long ago. Its state is
 * the tickets list's, so it reads as the ticket is now, not as it was when it was viewed.
 */
function JumpItem({
    value,
    ticketKey,
    title,
    summary,
    viewed,
    onSelect,
}: {
    value: string
    ticketKey: string
    title: string | null
    summary: TicketSummary | undefined
    viewed?: RecentTicket
    onSelect: () => void
}) {
    return (
        <CommandItem value={value} onSelect={onSelect} className="h-9 gap-3" data-testid={`jump-${ticketKey}`}>
            <span className="w-20 shrink-0 truncate font-mono text-xs">{ticketKey}</span>
            {title === null ? (
                <span className="min-w-0 flex-1 truncate text-muted-foreground">untitled</span>
            ) : (
                <span className="min-w-0 flex-1 truncate font-medium">{title}</span>
            )}
            {summary !== undefined && <Standing ticket={summary} />}
            {viewed !== undefined && <Viewed at={viewed.viewedAt} />}
        </CommandItem>
    )
}

/**
 * Where a ticket stands, in a line: the run working it, the question waiting on the operator, its plan waiting on
 * them, each in its state's color, else its phase, muted, or `done`.
 */
function Standing({ ticket }: { ticket: TicketSummary }) {
    const line = 'flex max-w-44 shrink-0 items-center gap-1.5 font-mono text-xs whitespace-nowrap'
    if (ticket.awaiting !== null) {
        return (
            <span className={cn(line, RUN_TEXT.blocked)}>
                <RunDot state="blocked" />
                waiting on you
            </span>
        )
    }
    if (ticket.plan_waits) {
        return (
            <span className={cn(line, RUN_TEXT.blocked)}>
                <RunDot state="blocked" />
                plan waits
            </span>
        )
    }
    if (ticket.running_run !== null) {
        return (
            <span className={cn(line, RUN_TEXT.running)}>
                <RunDot state="running" />
                {runRef(ticket.running_run)}
            </span>
        )
    }
    return (
        <span className={cn(line, 'text-muted-foreground')}>
            <span className="truncate">{ticket.done ? 'done' : phaseLabel(ticket)}</span>
        </span>
    )
}

/** How long ago a ticket was viewed, its number a readout, as an age reads everywhere. */
function Viewed({ at }: { at: string }) {
    const now = useNow()
    return (
        <time dateTime={at} className="w-14 shrink-0 text-right text-xs whitespace-nowrap text-muted-foreground">
            <span className="readout">{age(at, now)}</span> ago
        </time>
    )
}

/** What the list says when no ticket matches: that, and the journal's search for the words, once there are enough. */
function NoMatch({ text, onSearch }: { text: string; onSearch: (() => void) | undefined }) {
    return (
        <>
            <p className="px-2 pt-4 pb-2 text-center text-xs text-muted-foreground">
                no ticket with “{text.trim()}” in the key or title
            </p>
            {onSearch !== undefined && (
                <CommandItem value="search" onSelect={onSearch} className="h-9">
                    <Search aria-hidden className="text-muted-foreground" />
                    <span className="min-w-0 truncate">
                        Search the journal for <span className="font-medium">“{text.trim()}”</span>
                    </span>
                </CommandItem>
            )}
        </>
    )
}

/** The palette's keys, under its list: how to move, open, and close. */
function Keys() {
    return (
        <p aria-hidden className="flex items-center gap-4 border-t px-3 py-2 text-2xs text-muted-foreground">
            <span className="flex items-center gap-1.5">
                <Kbd>↑</Kbd>
                <Kbd>↓</Kbd>
                move
            </span>
            <span className="flex items-center gap-1.5">
                <Kbd>Enter</Kbd>
                open
            </span>
            <span className="flex items-center gap-1.5">
                <Kbd>Esc</Kbd>
                close
            </span>
        </p>
    )
}
