import { useSyncExternalStore } from 'react'

import { SECTIONS } from '@/lib/sections'
import type { Section } from '@/lib/sections'

/**
 * Sprig, the helper at the foot of the side rail (src/components/shell/buddy.tsx): a bent wire with a sprig on top,
 * offering tips nobody asked for. Its tips are plain strings written here, never journal text, and none of them is
 * real: a line that names something real belongs in the ticker's tips, which open with "Tip:", so Sprig's jokes open
 * with "Unhelpful tip:" or none at all. It is off until Settings turns it on, which is kept in localStorage like the
 * theme, and synced across tabs.
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
        'It looks like something needs you. Have you tried needing it back?',
        'Unhelpful tip: the most severe item is at the top. I put my favourite at the top too. It is me.',
    ],
    '/runs': [
        "It looks like you're watching runs. A watched run never finishes. (Unconfirmed.)",
        'Unhelpful tip: a run that has cost nothing has probably not started.',
        'It looks like a worker is working. Would you like me to make it nervous?',
    ],
    '/worktrees': [
        "It looks like you're counting worktrees. I can count to three. Please keep it to three.",
        'Unhelpful tip: a held worktree is not a free worktree. I came up with that myself.',
    ],
    '/tickets': [
        "It looks like you're reading a ticket. Would you like me to read it louder?",
        'Unhelpful tip: Forget makes canopy forget a ticket. I forget tickets for free, all day.',
        'It looks like you want to reply. Have you considered replying?',
    ],
    '/pull-requests': [
        "It looks like you're reading pull requests. I'd approve them all, but nobody lets me.",
        'Unhelpful tip: a PR with no reviews is a PR nobody has disappointed yet.',
    ],
    '/reviews': [
        "It looks like you're reading a review nobody posted. Your secret's safe with me.",
        'Unhelpful tip: every finding is a compliment, if you squint.',
    ],
    '/chores': [
        "It looks like you're doing chores. I'm so proud of you.",
        'Unhelpful tip: a chore runs when the overseer says so. Like bedtime.',
    ],
    '/ticks': [
        "It looks like you're reading the overseer's reasons. Don't tell it I showed you.",
        'Unhelpful tip: every tick has an id. I have an id too. It is Sprig.',
    ],
    '/settings': [
        "It looks like you're in Settings. You can turn me off here. I'd rather you didn't.",
        'Unhelpful tip: the Spicy ticker is for professionals.',
        'Unhelpful tip: every dollar canopy spends buys me hats. I would like the crown.',
    ],
    '/search': [
        "It looks like you're searching. I lost a leaf in 2024. Let me know if it turns up.",
        'Unhelpful tip: to find something, search for it. You are welcome.',
    ],
}

/** Sprig's tips for any page, after the page's own. */
export const ANYWHERE: readonly string[] = [
    "It looks like you're writing a letter. You aren't? Fair enough.",
    'Did you know? A leaf is a tree that went into solar.',
    "Unhelpful tip: I can't do anything, but I can do it enthusiastically.",
    "It looks like you're busy. I'll just be down here. Watching.",
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
