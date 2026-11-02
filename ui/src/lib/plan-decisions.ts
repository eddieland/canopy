// A plan's open decisions (docs/design/PLANNING.md §25): the choices its ticket left open, which the planner writes
// under `## Decisions` in one shape (.agents/prompts/worker-plan.md), so the plan's page can offer each as a choice:
//
//     ### Decision 2: Where a schedule's hour is kept
//
//     - **A (chosen):** In the owner's timezone: the ticket asks for the owner's hour.
//     - **B:** In UTC: simpler to store, but the hour moves when the clocks change.
//
// The operator answers one by picking another option, which goes with Approve to the implement, or with Ask for
// changes to the planner, as a line of their notes (`decisionAnswers`). A plan written before this shape, or one that
// strays from it, has fewer decisions or none: what does not parse is left out, and nothing here throws.

/** One option of an open decision. */
export interface PlanOption {
    /** Its letter, `A` for the first. */
    letter: string
    /** What it says, after its letter, with its Markdown bold dropped. */
    text: string
}

/** A choice the ticket left open, as the plan asks it. */
export interface PlanDecision {
    /** Its number, as its heading gives it: `2` for `### Decision 2`. Unique among the plan's decisions. */
    number: number
    /** What it asks, its heading's words after the number, with its Markdown bold dropped. */
    question: string
    /** Its options, in the plan's order, at least two, each letter once. */
    options: PlanOption[]
    /** The letter of the option the planner chose, which the plan follows. */
    chosen: string
}

/** How much of a decision's question an answer quotes: enough to tell it from the others beside its number. */
export const MAX_QUESTION = 60

// A heading, as CommonMark has it: one to six `#`, then a space or the line's end, indented at most three spaces.
const HEADING = /^ {0,3}(#{1,6})(?:[ \t]+(.*?))?(?:[ \t]+#+)?[ \t]*$/u
// The heading that opens a decision: its number, then its question after a colon, a full stop, or a dash.
const DECISION = /^Decision[ \t]+(\d{1,4})[ \t]*[:.–—-][ \t]*(\S.*)$/iu
// An option: a list item led by its letter in bold, `(chosen)` after the letter on the planner's choice, and a colon
// inside the bold or just after it.
const OPTION = /^ {0,3}[-*+][ \t]+\*\*([A-Z])([ \t]*\(chosen\))?[ \t]*:?\*\*[ \t]*:?[ \t]*(.*)$/iu
// A fence's opening or closing marker, indented at most three spaces.
const FENCE = /^ {0,3}(`{3,}|~{3,})/u

/**
 * The open decisions under a plan's `## Decisions`, in its order: each `### Decision N: <question>` heading with its
 * options, lettered list items with the planner's choice marked `(chosen)`. A decision with fewer than two options, an
 * option with no words, a letter twice, a number another took, or not exactly one choice, is left out, as is all of a
 * plan without the section.
 */
export function planDecisions(markdown: string): PlanDecision[] {
    const found: PlanDecision[] = []
    let inSection = false
    let current: Draft | undefined
    for (const line of unfenced(markdown)) {
        const heading = HEADING.exec(line)
        if (heading !== null) {
            const level = heading[1]?.length ?? 0
            const words = heading[2]?.trim() ?? ''
            finish(current, found)
            current = undefined
            if (level <= 2) {
                inSection = level === 2 && /^decisions$/iu.test(words)
            } else if (inSection) {
                current = opened(words)
            }
            continue
        }
        if (current !== undefined) {
            read(current, line)
        }
    }
    finish(current, found)
    return found
}

/**
 * What the operator's picks answer, a line each, in the plan's order: `Decision 2 (<question>): take B, not A.` for
 * each decision whose pick is an option other than the planner's choice. A pick the plan no longer offers, as after an
 * edit, answers nothing. Empty when every pick is the planner's.
 */
export function decisionAnswers(decisions: readonly PlanDecision[], picks: ReadonlyMap<number, string>): string[] {
    return decisions.flatMap((decision) => {
        const pick = picks.get(decision.number)
        if (pick === undefined || pick === decision.chosen || !decision.options.some((o) => o.letter === pick)) {
            return []
        }
        return [
            `Decision ${decision.number} (${cutQuestion(decision.question)}): take ${pick}, not ${decision.chosen}.`,
        ]
    })
}

// A decision as it is read, before its options are known to make one.
interface Draft {
    number: number
    question: string
    options: { letter: string; chosen: boolean; text: string }[]
    // Whether the last line read was its last option's, or a line under it, so an indented line continues it.
    open: boolean
}

// The plan's lines outside fenced code, where a `#` or a `- **A:**` is code, not the plan's own.
function unfenced(markdown: string): string[] {
    const lines: string[] = []
    let fence = ''
    for (const line of markdown.split(/\r?\n/u)) {
        const marker = FENCE.exec(line)?.[1]
        if (fence !== '') {
            // Closed by a marker of the same character, at least as long.
            if (marker?.startsWith(fence) === true) {
                fence = ''
            }
        } else if (marker === undefined) {
            lines.push(line)
        } else {
            fence = marker
        }
    }
    return lines
}

// A decision opened by its heading's words, or none for a heading that does not name one.
function opened(words: string): Draft | undefined {
    const match = DECISION.exec(words)
    if (match === null) {
        return undefined
    }
    return { number: Number(match[1]), question: plain(match[2] ?? ''), options: [], open: false }
}

// One line under a decision's heading: a new option, a line that continues the last, or prose that ends it.
function read(draft: Draft, line: string): void {
    const option = OPTION.exec(line)
    if (option !== null) {
        const [, letter = '', chosen, text = ''] = option
        draft.options.push({ letter: letter.toUpperCase(), chosen: chosen !== undefined, text: plain(text) })
        draft.open = true
        return
    }
    const last = draft.options.at(-1)
    if (line.trim() === '') {
        return
    }
    if (last !== undefined && draft.open && /^\s{2}/u.test(line)) {
        last.text = plain(`${last.text} ${line}`)
        return
    }
    draft.open = false
}

// The decision read, kept when it holds together: two options or more, each with words and its letter once, one chosen,
// and its number new.
function finish(draft: Draft | undefined, found: PlanDecision[]): void {
    if (draft === undefined || draft.question === '' || draft.options.length < 2) {
        return
    }
    if (draft.options.some((option) => option.text === '')) {
        return
    }
    const letters = new Set(draft.options.map((option) => option.letter))
    const chosen = draft.options.filter((option) => option.chosen)
    const first = chosen[0]
    if (letters.size !== draft.options.length || chosen.length !== 1 || first === undefined) {
        return
    }
    if (found.some((decision) => decision.number === draft.number)) {
        return
    }
    found.push({
        number: draft.number,
        question: draft.question,
        options: draft.options.map(({ letter, text }) => ({ letter, text })),
        chosen: first.letter,
    })
}

// Words as the page shows them: their whitespace collapsed and Markdown's bold dropped, its code spans kept.
function plain(text: string): string {
    return text.replaceAll('**', '').replaceAll(/\s+/gu, ' ').trim()
}

// A question as an answer quotes it: cut to `MAX_QUESTION` characters, at a word when one ends near the cut.
function cutQuestion(question: string): string {
    if (question.length <= MAX_QUESTION) {
        return question
    }
    const head = question.slice(0, MAX_QUESTION)
    const space = head.lastIndexOf(' ')
    return `${space > MAX_QUESTION / 2 ? head.slice(0, space) : head}…`
}
