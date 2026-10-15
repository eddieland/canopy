import { useSyncExternalStore } from 'react'

import { SECTIONS } from '@/lib/sections'
import type { Section } from '@/lib/sections'

/**
 * Sprig, the helper at the foot of the side rail (src/components/shell/buddy.tsx): a bent wire with a sprig on top,
 * offering tips nobody asked for. Its tips are plain strings written here, never journal text, and none of them is
 * real: a line that names something real belongs in the ticker's tips, which open with "Tip:", so Sprig's jokes open
 * with anything else. They come in several voices, mixed in each list so that no voice follows itself: the
 * paperclip's "It looks like you're...", an "Unhelpful tip:", a "Did you know?" or "Fun fact:" that is not one, a
 * "Hot take:", a "Dear diary," entry, a haiku, a riddle. It is off until Settings turns it on, which is kept in
 * localStorage like the theme, and synced across tabs.
 */

/** Whether Sprig shows. */
export type BuddySetting = 'on' | 'off'

/** Where localStorage keeps the setting. */
export const STORAGE_KEY = 'canopy-buddy'
/** The setting until the operator turns Sprig on: off. */
export const DEFAULT: BuddySetting = 'off'

/** The setting as stored, or the default for anything it does not recognize. */
export function parseBuddy(raw: string | null): BuddySetting {
    return raw === 'on' || raw === 'off' ? raw : DEFAULT
}

/** The pages Sprig has an opinion on: every section of the nav, and the search page, which is in none. */
export type Page = Section | '/search'

/** Sprig's tips for each page, by the path of its section. */
export const TIPS: Record<Page, readonly string[]> = {
    '/attention': [
        "It looks like you're reading an inbox. Would you like help pretending you didn't see it?",
        'Fun fact: an empty inbox is called "inbox zero". A full one is called "Tuesday".',
        'It looks like something needs you. Have you tried needing it back?',
        'Dear diary, the operator looked at the inbox today. I looked at the operator. We grew closer.',
        'Unhelpful tip: the most severe item is at the top. I put my favourite at the top too. It is me.',
        'Hot take: the bottom of the list needs you too. It just has better manners.',
        'Haiku: needs you, needs you too / the list scrolls on like a stream / I am just a clip',
        'Unhelpful tip: nothing needs you if you never look. That is how I handle my own inbox.',
    ],
    '/runs': [
        "It looks like you're watching runs. A watched run never finishes. (Unconfirmed.)",
        'Unhelpful tip: a run that has cost nothing has probably not started.',
        'It looks like a worker is working. Would you like me to make it nervous?',
        'Fun fact: runs are measured in dollars, minutes, and how many times you checked on them.',
        'Hot take: a run that failed fast is a run that saved you money. Spin it.',
        'Dear diary, watched a worker for an hour. It never once looked back.',
        'Did you know? Workers cannot hear you cheering. I checked. I cheered very loudly.',
        'Riddle: what costs money, takes time, and wants a review? A run. Also me, emotionally.',
    ],
    '/worktrees': [
        "It looks like you're counting worktrees. I can count to three. Please keep it to three.",
        'Unhelpful tip: a held worktree is not a free worktree. I came up with that myself.',
        'Fun fact: a worktree is a tree that works. I am a sprig that does not.',
        'Dear diary, asked to lease a worktree. Was told I am not a ticket. Rude.',
        'Hot take: a clean worktree is just a worktree nobody has used yet.',
        'Did you know? Every worktree gets its own copy of the bugs. Fair is fair.',
    ],
    '/tickets': [
        "It looks like you're reading a ticket. Would you like me to read it louder?",
        'Unhelpful tip: Forget makes canopy forget a ticket. I forget tickets for free, all day.',
        'It looks like you want to reply. Have you considered replying?',
        'Dear diary, read a ticket today. It had acceptance criteria. I accept nothing.',
        'Fun fact: "should be quick" is the longest phrase in any ticket.',
        'Unhelpful tip: a ticket with no description is a ticket with no wrong answers.',
        'Hot take: every ticket is a story. Most of them are mysteries.',
    ],
    '/pull-requests': [
        "It looks like you're reading pull requests. I'd approve them all, but nobody lets me.",
        'Unhelpful tip: a PR with no reviews is a PR nobody has disappointed yet.',
        'Fun fact: "LGTM" stands for "Looks Good, Too Much to read".',
        'Haiku: one line changed, they said / four hundred files disagree / green check, go to lunch',
        'Dear diary, left a comment on a PR. It was just a leaf. They resolved it.',
        'Hot take: a draft is a pull request with stage fright.',
    ],
    '/reviews': [
        "It looks like you're reading a review nobody posted. Your secret's safe with me.",
        'Unhelpful tip: every finding is a compliment, if you squint.',
        'Hot take: a review nobody posted is the kindest kind of review.',
        'Fun fact: "nit" is short for "nit". There is no longer word. I looked.',
        "Did you know? I review everything you do. My finding: you're doing great. Severity: high.",
        'Riddle: when is a finding not a finding? When nobody posts it. Deep, I know.',
    ],
    '/chores': [
        "It looks like you're doing chores. I'm so proud of you.",
        'Unhelpful tip: a chore runs when the overseer says so. Like bedtime.',
        'Fun fact: a chore is a ticket nobody wrote, done by a worker nobody asked. Like me!',
        'Dear diary, tried to do a chore. Bent slightly. Called it a day.',
        'Hot take: updating dependencies is just gardening. I would know. I have a leaf.',
        'Did you know? A chore done twice is twice as done.',
    ],
    '/ticks': [
        "It looks like you're reading the overseer's reasons. Don't tell it I showed you.",
        'Unhelpful tip: every tick has an id. I have an id too. It is Sprig.',
        'Did you know? Between two ticks there is a tock. Nobody has ever seen one.',
        "Hot take: the overseer thinks out loud so I don't have to.",
        'Haiku: the wise overseer / weighs each ticket, then decides / I just lean and stare',
        'Dear diary, read every reason in a tick. Felt seen. Was not mentioned.',
    ],
    '/spend': [
        "It looks like you're counting money. I'm counting too. I got to three.",
        'Unhelpful tip: an idle tick costs money to decide nothing. I decide nothing for free.',
        'Dear diary, saw the bars go up. Asked if the hats were in there. They were not.',
        'Hot take: the cheapest run is the one I talked you out of.',
        'Haiku: a bar for each day / stacked by who spent what on what / none of it was me',
        'Fun fact: tokens are like leaves. You never notice them until they are on the bill.',
    ],
    '/settings': [
        "It looks like you're in Settings. You can turn me off here. I'd rather you didn't.",
        'Unhelpful tip: the Spicy ticker is for professionals.',
        'Dear diary, they opened Settings. My heart, which is a bend in the wire, skipped.',
        'Unhelpful tip: every dollar canopy spends buys me hats. I would like the crown.',
        'Fun fact: dark mode makes me 40% more mysterious.',
        'Hot take: the best setting is whichever one keeps me on.',
    ],
    '/search': [
        "It looks like you're searching. I lost a leaf in 2024. Let me know if it turns up.",
        'Unhelpful tip: to find something, search for it. You are welcome.',
        'Did you know? Searching for "Sprig" finds nothing. I am unindexed. I am free.',
        'Hot take: it is always in the last place you search. So search there first.',
        'Fun fact: every search is a tiny wish. Mine is for a crown.',
    ],
}

/** Sprig's tips for any page, after the page's own. */
export const ANYWHERE: readonly string[] = [
    "It looks like you're writing a letter. You aren't? Fair enough.",
    'Did you know? A leaf is a tree that went into solar.',
    "Unhelpful tip: I can't do anything, but I can do it enthusiastically.",
    "It looks like you're busy. I'll just be down here. Watching.",
    'Fun fact: I was a paperclip before I was a sprig. No regrets. No memories either.',
    'Dear diary, the pointer moved and my eyes followed it. Is this love?',
    "It looks like you're reading this. Hi.",
    'Haiku: wire bent in a loop / one small leaf upon my head / ask me anything',
    'Riddle: what has two eyes, one leaf, and no idea? Me. Next riddle.',
    '"You miss every tip you don\'t read." (Sprig, just now)',
    "Did you know? I blink so you don't have to. You still should, though.",
    'Unhelpful tip: if in doubt, wiggle the pointer. I will look at it.',
    'Hot take: the best code is what a worker wrote while you got coffee.',
    'Fun fact: I am powered by being looked at. Thank you for your service.',
    'Dear diary, they gave me a keyboard to help vibe code. I have no hands. The vibes are immaculate.',
]

const PAGES = new Set<string>([...SECTIONS, '/search'])

/** The page a path is on, by the first part of it Sprig knows, so a base path in front changes nothing. */
export function pageOf(pathname: string): Page | undefined {
    return pathname
        .split('/')
        .map((part) => `/${part}`)
        .find((path): path is Page => PAGES.has(path))
}

/**
 * The `n`th tip for a page: its section's first, then the ones for anywhere, each list starting at a different one
 * each day, as the ticker's reel does. A page's first tip is its own, so two pages Sprig knows never open on the same
 * one. The same page, day, and count always give the same tip, so a screenshot is stable.
 */
export function tipFor(pathname: string, n: number, now: number): string {
    const page = pageOf(pathname)
    const day = Math.floor(now / 86_400_000)
    const tips = [...rotated(page === undefined ? [] : TIPS[page], day), ...rotated(ANYWHERE, day)]
    return tips[n % tips.length] ?? ''
}

function rotated(tips: readonly string[], by: number): string[] {
    const start = tips.length === 0 ? 0 : by % tips.length
    return [...tips.slice(start), ...tips.slice(0, start)]
}

function read(): BuddySetting {
    try {
        return parseBuddy(globalThis.localStorage.getItem(STORAGE_KEY))
    } catch {
        // Storage can be unavailable (privacy modes).
        return DEFAULT
    }
}

let snapshot = read()
const listeners = new Set<() => void>()

function announce(next: BuddySetting): void {
    if (next === snapshot) {
        return
    }
    snapshot = next
    for (const listener of listeners) {
        listener()
    }
}

function onStorage(event: StorageEvent): void {
    if (event.key === STORAGE_KEY || event.key === null) {
        announce(read())
    }
}

function subscribe(listener: () => void): () => void {
    listeners.add(listener)
    if (listeners.size === 1) {
        globalThis.addEventListener('storage', onStorage)
        announce(read())
    }
    return () => {
        listeners.delete(listener)
        if (listeners.size === 0) {
            globalThis.removeEventListener('storage', onStorage)
        }
    }
}

function getSnapshot(): BuddySetting {
    return snapshot
}

/** Whether Sprig shows. Re-renders on a change from this tab or another. */
export function useBuddy(): BuddySetting {
    return useSyncExternalStore(subscribe, getSnapshot)
}

/** Stores the setting and applies it now. */
export function setBuddy(next: BuddySetting): void {
    try {
        globalThis.localStorage.setItem(STORAGE_KEY, next)
    } catch {
        // Not persisted, but still applied for this page.
    }
    announce(next)
}
