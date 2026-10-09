/**
 * The header ticker's headlines (src/components/shell/ticker.tsx): light razzing of programming and vibe coding, in
 * the spirit of a cartoon's title-card caption. Plain strings, written here; nothing from the journal.
 *
 * A headline can open with RuneScape chat flair, as a player would type it: a color, then an effect, each ending in a
 * colon (`flash2:wave:Now with...`). Either may be left out. See `parseHeadline`.
 */
export const HEADLINES: readonly string[] = [
    'flash2:wave:Now with 40% more vibes than the leading brand',
    'Works on my machine; machine declines to comment',
    'Agent says "You\'re absolutely right!" for the 19th time today',
    'Area man accepts all 412 suggested changes without reading one',
    'glow1:Dependency count now exceeds lines of code',
    'Off-by-one errors down 1% (or 2%)',
    'red:shake:Agent apologizes sincerely, then does it again',
    'Regex written; experts confirm there are now two problems',
    'Developer removes one console.log, app stops working',
    'Scientists find no upper bound on a "quick refactor"',
    'green:Unit tests pass; units not consulted',
    'Agent rewrites the test to match the bug, calls it alignment',
    'Context window full; agent forgets what a for loop is',
    'Startup pivots to AI-native by renaming utils.py',
    'It is not a bug, it is an emergent behavior',
    'glow3:wave:10x developer revealed to be ten agents in a trench coat',
    "Rubber duck files for workers' comp",
    'Linter finds 3,000 issues; developer finds a new linter',
    '"One small change" lands as +4,812 − 3',
    'cyan:wave2:Prompt engineer promoted to Principal Vibe Architect',
    'Local dev insists it is just one more prompt',
    'Exception swallowed whole; witnesses say it was delicious',
    'Cache invalidated; naming things still pending',
    'Senior engineer discovers a TODO they left in 2019',
    'Semicolons now optional, like reading the diff',
    'flash1:Ship it Friday, said nobody who shipped it Friday',
    'flash3:shake:A watched CI never turns green',
    'purple:Model hallucinates a library; library is published by lunch',
    'Treehouse at capacity; squirrels displaced',
    'Overseer reminds workers it can see them',
    'Worker pushes once and exits, as is its way',
    'Tabs versus spaces talks collapse; vibes declared the winner',
    'Code review approved with a single "lgtm, vibes are immaculate"',
    'Stack Overflow answer from 2011 still holding up production',
    'white:wave:Loading witty headline...',
    'Recursion explained in full: see "Recursion explained in full"',
    'Dark mode on, which is to say it is 2 a.m.',
    'Agent "fixes" flaky test by deleting the flake, and the test',
    'flash1:wave:Free trimmed armour! Just approve my PR first',
    'glow2:Agent hits 99 Debugging; bug still at large',
    'yellow:wave2:Doubling your test coverage, trust me',
]

/** RuneScape's chat colors. A flash alternates two colors; a glow cycles through several. */
export const FLAIR_COLORS = [
    'yellow',
    'red',
    'green',
    'cyan',
    'purple',
    'white',
    'flash1',
    'flash2',
    'flash3',
    'glow1',
    'glow2',
    'glow3',
] as const
/** RuneScape's chat effects, letter by letter. Its `scroll` is the ticker itself; `slide` happens off screen. */
export const FLAIR_EFFECTS = ['wave', 'wave2', 'shake'] as const

export type FlairColor = (typeof FLAIR_COLORS)[number]
export type FlairEffect = (typeof FLAIR_EFFECTS)[number]

export interface Headline {
    text: string
    color?: FlairColor
    effect?: FlairEffect
}

const FLAIR = new RegExp(`^(?:(${FLAIR_COLORS.join('|')}):)?(?:(${FLAIR_EFFECTS.join('|')}):)?`)

/** A headline's text and its flair, read off its front: a color, then an effect, either one optional. */
export function parseHeadline(line: string): Headline {
    const match = FLAIR.exec(line)
    const color = match?.[1] as FlairColor | undefined
    const effect = match?.[2] as FlairEffect | undefined
    return { text: line.slice(match?.[0].length ?? 0), ...(color && { color }), ...(effect && { effect }) }
}

const DAY_MS = 86_400_000

/** Every headline once, starting at a different one each day, so a regular reader does not always see the same lead. */
export function headlinesFor(now: number): string[] {
    const start = Math.floor(now / DAY_MS) % HEADLINES.length
    return [...HEADLINES.slice(start), ...HEADLINES.slice(0, start)]
}
