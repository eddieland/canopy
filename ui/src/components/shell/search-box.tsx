import { useMatchRoute, useNavigate, useSearch } from '@tanstack/react-router'
import { Search, X } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'

import { Button } from '@/components/ui/button'
import { Kbd } from '@/components/ui/kbd'
import { isSearchShortcut, SEARCH_DEBOUNCE_MS, SEARCH_MAX, searchQueryOf } from '@/lib/search'
import { cn } from '@/lib/utils'

/**
 * The search box atop the nav, on every page (DESIGN §22, Search). `/` focuses it from anywhere but a text field, and
 * Escape leaves it. Typing opens the search page once the operator pauses, replacing the history entry while the page
 * is open, so Back leaves the search rather than stepping through each keystroke; Enter opens it at once. While it
 * holds text, a clear button takes the keycap's place: it empties the box and keeps the focus there. Emptying the box,
 * by the button or by deleting its text, clears the search page if it is open, and leaves any other page as it is.
 */
export function SearchBox() {
    const navigate = useNavigate()
    const matchRoute = useMatchRoute()
    const q = useSearch({ strict: false, select: (s) => searchQueryOf(s.q) })
    const [value, setValue] = useState(q ?? '')
    // What the page's query was when the box last looked: Back or a link changing it shows the new one in the box.
    const [seen, setSeen] = useState(q)
    if (q !== seen) {
        setSeen(q)
        if (q !== undefined) {
            setValue(q)
        }
    }
    const input = useRef<HTMLInputElement>(null)
    const timer = useRef<number | undefined>(undefined)

    useEffect(() => {
        function onKey(event: KeyboardEvent) {
            if (!isSearchShortcut(event, event.target)) {
                return
            }
            event.preventDefault()
            input.current?.focus()
            input.current?.select()
        }
        globalThis.addEventListener('keydown', onKey)
        return () => {
            globalThis.removeEventListener('keydown', onKey)
            globalThis.clearTimeout(timer.current)
        }
    }, [])

    function open(text: string) {
        globalThis.clearTimeout(timer.current)
        const onPage = matchRoute({ to: '/search' }) !== false
        const query = searchQueryOf(text)
        if (query === undefined) {
            // An empty box empties the search page; a query too short to send leaves the last one's hits in place.
            if (onPage && text.trim() === '') {
                void navigate({ to: '/search', search: { q: undefined }, replace: true })
            }
            return
        }
        void navigate({ to: '/search', search: { q: query }, replace: onPage })
    }

    function clear() {
        setValue('')
        open('')
        input.current?.focus()
    }

    return (
        <search className="px-2 pt-2">
            <form
                onSubmit={(event) => {
                    event.preventDefault()
                    open(value)
                }}
                className={cn(
                    'flex h-8 items-center gap-2 rounded-md border bg-surface-raised px-2.5',
                    'focus-within:border-ring focus-within:ring-3 focus-within:ring-ring/50',
                )}
            >
                <Search aria-hidden className="size-3.5 shrink-0 text-muted-foreground" />
                <input
                    ref={input}
                    type="search"
                    aria-label="Search the journal"
                    aria-keyshortcuts="/"
                    placeholder="Search"
                    maxLength={SEARCH_MAX}
                    value={value}
                    onChange={(event) => {
                        const text = event.target.value
                        setValue(text)
                        globalThis.clearTimeout(timer.current)
                        timer.current = globalThis.setTimeout(() => open(text), SEARCH_DEBOUNCE_MS)
                    }}
                    onKeyDown={(event) => {
                        if (event.key === 'Escape') {
                            event.currentTarget.blur()
                        }
                    }}
                    className={cn(
                        'min-w-0 flex-1 bg-transparent text-sm text-foreground outline-none',
                        'placeholder:text-muted-foreground [&::-webkit-search-cancel-button]:hidden',
                    )}
                />
                {value ? (
                    <Button
                        type="button"
                        variant="ghost"
                        size="icon-xs"
                        aria-label="Clear search"
                        onClick={clear}
                        className="hover:bg-muted"
                    >
                        <X aria-hidden />
                    </Button>
                ) : (
                    <Kbd aria-hidden>/</Kbd>
                )}
            </form>
        </search>
    )
}
