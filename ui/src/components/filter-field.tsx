import { useState } from 'react'

import { SearchField } from '@/components/input'

/**
 * A list's text filter, kept in its page's `?q=` (`q`): the list narrows as the operator types, `onFilter` taking the
 * text as `queryOf` keeps it, and Escape leaves the field. The page replaces the history entry on each keystroke, so
 * Back leaves the page rather than stepping through each one; Back or a link changing `?q=` shows the new text here.
 */
export function FilterField({
    q,
    queryOf,
    onFilter,
    label,
    placeholder,
    maxLength,
    className,
}: {
    /** The page's validated `?q=`. */
    q: string | undefined
    /** The text as the page keeps it in `?q=`, or undefined when it holds no word. */
    queryOf: (text: string) => string | undefined
    /** Sets the page's `?q=`. */
    onFilter: (query: string | undefined) => void
    /** The field's name, for a screen reader. */
    label: string
    /** What the empty field says. */
    placeholder: string
    /** The longest text the page keeps. */
    maxLength: number
    /** Classes for the field's box, such as its width. */
    className?: string
}) {
    const [value, setValue] = useState(q ?? '')
    // What `?q=` was when the field last looked, so a change from outside it shows there.
    const [seen, setSeen] = useState(q)
    if (q !== seen) {
        setSeen(q)
        setValue(q ?? '')
    }

    function filter(text: string) {
        const query = queryOf(text)
        setValue(text)
        setSeen(query)
        onFilter(query)
    }

    return (
        <SearchField
            aria-label={label}
            placeholder={placeholder}
            maxLength={maxLength}
            value={value}
            onChange={(event) => filter(event.target.value)}
            onKeyDown={(event) => {
                if (event.key === 'Escape') {
                    event.currentTarget.blur()
                }
            }}
            onClear={() => filter('')}
            clearLabel="Clear the filter"
            className={className}
        />
    )
}
