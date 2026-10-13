import { useSyncExternalStore } from 'react'

/**
 * Sprig, the helper in the page's corner (src/components/shell/buddy.tsx): a bent wire with a sprig on top, offering
 * tips nobody asked for. Its tips are plain strings written here, never journal text. It is off until Settings turns it
 * on, which is kept in localStorage like the theme, and synced across tabs.
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

/** The pages Sprig has an opinion on, by the first part of their path. */
export type Section = 'attention' | 'runs' | 'worktrees' | 'tickets' | 'chores' | 'ticks' | 'settings'

/** Sprig's tips for each page it knows, and for anywhere. */
export const TIPS: Record<Section | 'anywhere', readonly string[]> = {
    attention: [
        "It looks like you're reading an inbox. Would you like help pretending you didn't see it?",
        'It looks like something needs you. Have you tried needing it back?',
        'Tip: the most severe item is at the top. I put my favourite at the top too. It is me.',
    ],
    runs: [
        "It looks like you're watching runs. A watched run never finishes. (Unconfirmed.)",
        'Tip: a run that has cost nothing has probably not started.',
        'It looks like a worker is working. Would you like me to make it nervous?',
    ],
    worktrees: [
        "It looks like you're counting worktrees. I can count to three. Please keep it to three.",
        'Tip: a held worktree is not a free worktree. I came up with that myself.',
    ],
    tickets: [
        "It looks like you're reading a ticket. Would you like me to read it louder?",
        'Tip: Forget makes canopy forget a ticket. I forget tickets for free, all day.',
        'It looks like you want to reply. Have you considered replying?',
    ],
    chores: [
        "It looks like you're doing chores. I'm so proud of you.",
        'Tip: a chore runs when the overseer says so. Like bedtime.',
    ],
    ticks: [
        "It looks like you're reading the overseer's reasons. Don't tell it I showed you.",
        'Tip: every tick has an id. I have an id too. It is Sprig.',
    ],
    settings: [
        "It looks like you're in Settings. You can turn me off here. I'd rather you didn't.",
        'Tip: the Spicy ticker is for professionals.',
    ],
    anywhere: [
        "It looks like you're writing a letter. You aren't? Fair enough.",
        'Did you know? A leaf is a tree that went into solar.',
        "Tip: I can't do anything, but I can do it enthusiastically.",
        "It looks like you're busy. I'll just be down here. Watching.",
    ],
}

const SECTIONS = new Set<string>(['attention', 'runs', 'worktrees', 'tickets', 'chores', 'ticks', 'settings'])

/** The section a path is in: its first part Sprig knows, so a base path in front changes nothing. */
export function sectionOf(pathname: string): Section | undefined {
    return pathname.split('/').find((part): part is Section => SECTIONS.has(part))
}

/**
 * The `n`th tip for a page: its section's and the ones for anywhere, starting at a different one each day, as the
 * ticker's reel does. The same page, day, and count always give the same tip, so a screenshot is stable.
 */
export function tipFor(pathname: string, n: number, now: number): string {
    const section = sectionOf(pathname)
    const tips = [...(section === undefined ? [] : TIPS[section]), ...TIPS.anywhere]
    const day = Math.floor(now / 86_400_000)
    return tips[(day + n) % tips.length] ?? ''
}

function read(): BuddySetting {
    try {
        return parseBuddy(window.localStorage.getItem(STORAGE_KEY))
    } catch {
        // Storage can be unavailable (privacy modes).
        return DEFAULT
    }
}

let snapshot = read()
const listeners = new Set<() => void>()

function announce(next: BuddySetting): void {
    if (next === snapshot) return
    snapshot = next
    for (const listener of listeners) listener()
}

function onStorage(event: StorageEvent): void {
    if (event.key === STORAGE_KEY || event.key === null) announce(read())
}

function subscribe(listener: () => void): () => void {
    listeners.add(listener)
    if (listeners.size === 1) {
        window.addEventListener('storage', onStorage)
        announce(read())
    }
    return () => {
        listeners.delete(listener)
        if (listeners.size === 0) window.removeEventListener('storage', onStorage)
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
        window.localStorage.setItem(STORAGE_KEY, next)
    } catch {
        // Not persisted, but still applied for this page.
    }
    announce(next)
}
