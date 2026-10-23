import { useMatchRoute, useNavigate, useSearch } from '@tanstack/react-router'
import { useEffect, useRef, useState } from 'react'

import { SearchField } from '@/components/input'
import { Kbd } from '@/components/ui/kbd'
import { JumpButton } from './jump-palette'
import { parseTaskRef } from '@/lib/refs'
import { isSearchShortcut, SEARCH_DEBOUNCE_MS, SEARCH_MAX, searchQueryOf } from '@/lib/search'

/**
 * The search box atop the nav, on every page (DESIGN §22, Search). `/` focuses it from anywhere but a text field, and
 * Escape leaves it. Typing opens the search page once the operator pauses, replacing the history entry while the page
 * is open, so Back leaves the search rather than stepping through each keystroke; Enter opens it at once, or, when the
 * box holds a task's reference alone (`task:4`), that task's page. While it holds text, a clear button takes the
 * keycap's place: it empties the box and keeps the focus there. Emptying the box, by the button or by deleting its
 * text, clears the search page if it is open, and leaves any other page as it is.
 * While it is empty, its end shows the `/` that focuses it and the ⌘K that opens the jump palette, which `onJump` does.
 */
export function SearchBox({ onJump }: { onJump: () => void }) {
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
    const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)

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
        <search className="px-2 pt-3">
            <form
                onSubmit={(event) => {
                    event.preventDefault()
                    const task = parseTaskRef(value)
                    if (task === undefined) {
                        open(value)
                        return
                    }
                    globalThis.clearTimeout(timer.current)
                    void navigate({ to: '/tasks/$id', params: { id: String(task) } })
                }}
            >
                <SearchField
                    ref={input}
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
                    onClear={clear}
                    clearLabel="Clear search"
                    idle={
                        <span className="flex items-center gap-1">
                            <Kbd aria-hidden>/</Kbd>
                            <JumpButton onOpen={onJump} />
                        </span>
                    }
                />
            </form>
        </search>
    )
}
