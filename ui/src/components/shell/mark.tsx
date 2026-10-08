/** The logo: a ring and a dot, in the accent color. */
export function Mark() {
    return (
        <svg viewBox="0 0 16 16" className="size-4 text-accent" aria-hidden>
            <circle cx="8" cy="8" r="6.25" fill="none" stroke="currentColor" strokeWidth="1.5" />
            <circle cx="8" cy="8" r="2" fill="currentColor" />
        </svg>
    )
}
