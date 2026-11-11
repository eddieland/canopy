// A plan printed, or saved as a PDF from the print dialog, as a document: the plan alone under a line naming it, in the
// light theme whatever the screen shows (the rules are `:root[data-printing='plan']` in src/index.css). The browser
// says it is about to print (`beforeprint`) and has printed (`afterprint`), so the page takes the light theme for the
// print, and gives it back after. A diagram's picture is drawn in the theme it was drawn in, and a print does not wait
// for one drawn again, so a picture drawn dark is marked (`data-drawn-dark`, src/lib/plan-diagram.ts) and printed with
// its light and dark turned round, its hues kept.

// Where a plan stands, in the page's words for it: a proposed plan is one that waits on the operator.
const STATUS_WORDS: Partial<Record<string, string>> = { proposed: 'waiting on you' }

/** The line a printed plan opens with: its ticket or epic, which plan, where it stands, and when it was written. */
export function printLine(subject: string, plan: number, status: string, written: string): string {
    const date = new Date(written).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
    return `${subject} · plan ${plan} · ${STATUS_WORDS[status] ?? status} · written ${date}`
}

/**
 * While a page shows a plan to print: before each print the page takes the light theme and marks itself printing a
 * plan, and after it, gets its own theme back. Returns what stops it.
 */
export function printsAPlan(): () => void {
    const root = document.documentElement
    let dark = false
    const before = () => {
        dark = root.classList.contains('dark')
        root.classList.remove('dark')
        root.dataset['printing'] = 'plan'
    }
    const after = () => {
        root.classList.toggle('dark', dark || root.classList.contains('dark'))
        delete root.dataset['printing']
    }
    globalThis.addEventListener('beforeprint', before)
    globalThis.addEventListener('afterprint', after)
    return () => {
        globalThis.removeEventListener('beforeprint', before)
        globalThis.removeEventListener('afterprint', after)
    }
}
