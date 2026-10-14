/**
 * The header ticker's headlines (src/components/shell/ticker.tsx), by topic: light razzing of programming and of vibe
 * coding, in the spirit of a cartoon's title-card caption, and tips for using canopy. Plain strings, written here;
 * nothing from the journal. The ticker picks each one at random from the topics Settings leaves on
 * (src/lib/ticker-settings.ts). A new topic is a name in TICKER_TOPICS, its headlines, and its label in Settings.
 *
 * A headline can open with RuneScape chat flair, as a player would type it: a color, then an effect, each ending in a
 * colon (`flash2:wave:Now with...`). Either may be left out. See `parseHeadline`. A tip opens with `Tip: ` instead,
 * so it reads as one among the jokes, and has no flair.
 */

/** The ticker's topics, in the order Settings lists them. */
export const TICKER_TOPICS = ['programming', 'vibes', 'tips'] as const

/** One of the ticker's topics, each of which Settings can turn off. */
export type TickerTopic = (typeof TICKER_TOPICS)[number]

/** Every headline, by topic. */
export const HEADLINES: Record<TickerTopic, readonly string[]> = {
    programming: [
        'Works on my machine; machine declines to comment',
        'glow1:Dependency count now exceeds lines of code',
        'Off-by-one errors down 1% (or 2%)',
        'Regex written; experts confirm there are now two problems',
        'Developer removes one console.log, app stops working',
        'Scientists find no upper bound on a "quick refactor"',
        'green:Unit tests pass; units not consulted',
        'It is not a bug, it is an emergent behavior',
        "Rubber duck files for workers' comp",
        'Linter finds 3,000 issues; developer finds a new linter',
        '"One small change" lands as +4,812 − 3',
        'Exception swallowed whole; witnesses say it was delicious',
        'Cache invalidated; naming things still pending',
        'Senior engineer discovers a TODO they left in 2019',
        'flash1:Ship it Friday, said nobody who shipped it Friday',
        'flash3:shake:A watched CI never turns green',
        'Tabs versus spaces talks collapse; vibes declared the winner',
        'Stack Overflow answer from 2011 still holding up production',
        'white:wave:Loading witty headline...',
        'Recursion explained in full: see "Recursion explained in full"',
        'Dark mode on, which is to say it is 2 a.m.',
        'flash1:wave:Free trimmed armour! Just approve my PR first',
    ],
    vibes: [
        'flash2:wave:Now with 40% more vibes than the leading brand',
        'Agent says "You\'re absolutely right!" for the 19th time today',
        'Area man accepts all 412 suggested changes without reading one',
        'red:shake:Agent apologizes sincerely, then does it again',
        'Agent rewrites the test to match the bug, calls it alignment',
        'Context window full; agent forgets what a for loop is',
        'Startup pivots to AI-native by renaming utils.py',
        'glow3:wave:10x developer revealed to be ten agents in a trench coat',
        'cyan:wave2:Prompt engineer promoted to Principal Vibe Architect',
        'Local dev insists it is just one more prompt',
        'Semicolons now optional, like reading the diff',
        'purple:Model hallucinates a library; library is published by lunch',
        'Treehouse at capacity; squirrels displaced',
        'Overseer reminds workers it can see them',
        'Worker pushes once and exits, as is its way',
        'Code review approved with a single "lgtm, vibes are immaculate"',
        'Agent "fixes" flaky test by deleting the flake, and the test',
        'glow2:Agent hits 99 Debugging; bug still at large',
        'yellow:wave2:Doubling your test coverage, trust me',
    ],
    tips: [
        'Tip: press / anywhere but a text field to search tickets, messages, and decisions',
        "Tip: press t during canopy loop's countdown to tick now",
        "Tip: press p at canopy loop's terminal to pause it, and p again to resume",
        'Tip: canopy pause holds the next tick; workers already running keep going',
        "Tip: canopy tick --dry-run shows the overseer's plan and dispatches nothing",
        "Tip: canopy decisions --ticket KEY prints the latest tick's plan for one ticket",
        'Tip: canopy reply KEY answers a ticket, and a waiting loop wakes for it',
        'Tip: canopy start KEY works a ticket privately; nothing canopy writes reaches it',
        'Tip: canopy stop KEY --now also ends the run working it',
        'Tip: canopy grant KEY implement allows one more run past the attempt limit',
        'Tip: canopy forget KEY starts its next implement over on a new branch',
        'Tip: canopy show run:ID shows one run, and chore:NAME a chore',
        'Tip: canopy chore try NAME runs a chore now, in the foreground',
        'Tip: Reload in Settings, or kill -HUP, has the loop read its config again',
        'Tip: canopy skill prints a skill that teaches your own agent sessions canopy',
        'Tip: canopy secret --rotate, then a restart, signs every browser out',
        "Tip: a list's order toggle, in its panel header, flips it to oldest first",
        'Tip: Settings picks the key that sends a reply; Shift+Enter is always a new line',
        'Tip: hold the pointer over a headline to keep it still',
        'Tip: Settings turns off any of these topics, tips included',
        'Tip: Escape leaves the search box',
        'Tip: canopy status prints the attention list, started tickets, running workers, and recent runs',
        'Tip: canopy resume ticks at once if its wait has run out',
        'Tip: canopy loop --ticks N stops after N ticks',
        'Tip: canopy loop --every MINUTES sets the wait after each tick, and keeps it on a reload',
        'Tip: canopy loop --no-serve runs the loop without serving the web UI',
        "Tip: canopy decisions TICK_ID prints an older tick's decisions",
        "Tip: canopy review show lists the last 14 days' reviews; they post nothing on the PR",
        "Tip: canopy dismiss chore:NAME ID takes a chore's finding off the attention list; --undo takes it back",
        "Tip: canopy reply chore:NAME leaves a note the chore's next runs read, such as a finding to leave out",
        'Tip: canopy chore try NAME --no-record records nothing, for drafting a prompt',
        'Tip: canopy grant URL review lets a PR past policy.max_reviews_per_pr be reviewed again',
        'Tip: canopy forget never closes PRs or deletes branches; that part is yours',
        'Tip: canopy notify test sends a test message to every sink and changes nothing in the journal',
        'Tip: canopy workspace sync --dry-run says what sync would clone, make, and remove',
        'Tip: canopy workspace add URL adds a repository to the map, then syncs',
        'Tip: Settings turns on Sprig, the helper at the foot of the side rail; none of its tips help',
    ],
}

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

/** A headline's color flair, one of FLAIR_COLORS. */
export type FlairColor = (typeof FLAIR_COLORS)[number]
/** A headline's effect flair, one of FLAIR_EFFECTS. */
export type FlairEffect = (typeof FLAIR_EFFECTS)[number]

/** One headline for the ticker, its flair read off its front. */
export interface Headline {
    /** What the ticker shows. */
    text: string
    /** Its color, or the ticker's own when absent. */
    color?: FlairColor
    /** How its letters move, or not at all when absent. */
    effect?: FlairEffect
}

const FLAIR = new RegExp(`^(?:(${FLAIR_COLORS.join('|')}):)?(?:(${FLAIR_EFFECTS.join('|')}):)?`, 'u')

/** A headline's text and its flair, read off its front: a color, then an effect, either one optional. */
export function parseHeadline(line: string): Headline {
    const match = FLAIR.exec(line)
    const color = match?.[1] as FlairColor | undefined
    const effect = match?.[2] as FlairEffect | undefined
    return { text: line.slice(match?.[0].length ?? 0), ...(color && { color }), ...(effect && { effect }) }
}

/** Every headline of the topics not hidden. */
export function headlinesFor(hidden: readonly TickerTopic[] = []): string[] {
    return TICKER_TOPICS.filter((topic) => !hidden.includes(topic)).flatMap((topic) => HEADLINES[topic])
}

/**
 * Which of `count` headlines to show next: one at random, but never `last` while there is another, so no headline
 * follows itself. A `last` out of range picks from them all.
 */
export function nextIndex(count: number, last: number, random: () => number = Math.random): number {
    const skip = last >= 0 && last < count && count > 1
    const pick = Math.floor(random() * (skip ? count - 1 : count))
    return skip && pick >= last ? pick + 1 : pick
}
