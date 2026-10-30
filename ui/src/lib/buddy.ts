import { GHOST_ANYWHERE, GHOST_RAVE, GHOST_TIPS } from '@/lib/ghost'
import { nextIndex } from '@/lib/headlines'
import { storedSetting, useStoredSetting } from '@/lib/stored-setting'

/**
 * Sprig, the helper at the foot of the side rail (src/components/shell/buddy.tsx): a bent wire with a sprig on top,
 * offering tips nobody asked for, several of its own for each view. Its tips are plain strings written here, never
 * journal text, and none of them is real: a line that names something real belongs in the ticker's tips, which open
 * with "Tip:", so Sprig's jokes open with anything else. They come in several voices, mixed in each list so that no
 * voice follows itself: the paperclip's "It looks like you're...", an "Unhelpful tip:", a "Did you know?" or "Fun
 * fact:" that is not one, a "Hot take:", a "Dear diary," entry, a haiku, a riddle. While the lightswitch rave is on
 * (src/lib/rave.ts), Sprig has only the rave on its mind. It is off until Settings turns it on, which is kept in
 * localStorage like the theme, and synced across tabs. Settings can also put a Destiny Ghost in its place, with lines
 * of its own (src/lib/ghost.ts): the same setting turns either on and off.
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

/** Who sits at the foot of the rail while it is on: Sprig, or a Ghost in its place. */
export type Companion = 'sprig' | 'ghost'

/** Where localStorage keeps who sits there. */
export const COMPANION_KEY = 'canopy-companion'
/** Who sits there until the operator picks: Sprig. */
export const DEFAULT_COMPANION: Companion = 'sprig'

/** What each companion is called, on the rail and in Settings. */
export const NAMES: Record<Companion, string> = { sprig: 'Sprig', ghost: 'Ghost' }

/** Who sits there as stored, or the default for anything it does not recognize. */
export function parseCompanion(raw: string | null): Companion {
    return raw === 'sprig' || raw === 'ghost' ? raw : DEFAULT_COMPANION
}

/**
 * Sprig's tips for each view, by its route id: every route but those that only redirect, the root and the guide's. A
 * section's list and one of its items are views of their own (`/tickets/` and `/tickets/$key`). The routes are not
 * imported here, which would bring them all into the unit tests' types: src/components/shell/buddy.tsx holds them to
 * these keys, so a new route fails the type check until it has its own tips.
 */
export const TIPS = {
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
    '/tickets/': [
        'It looks like you\'re starting a ticket. Would you like me to write "fix it" in the title?',
        'Fun fact: "should be quick" is the longest phrase in any ticket.',
        'Hot take: every ticket is a story. Most of them are mysteries.',
        'Unhelpful tip: a ticket with no description is a ticket with no wrong answers.',
        'Dear diary, filtered the tickets to the ones waiting on you. It was all of them. Again.',
        'Riddle: what is open, blocked, and done all at once? Nothing. Please. Not a ticket.',
    ],
    '/tasks/': [
        "It looks like you're handing out tasks. Would you like one about watering me?",
        'Fun fact: a task is a ticket that skipped the meeting.',
        'Unhelpful tip: "find out why it\'s slow" is a task. "Make it fast" is a lifestyle.',
        'Dear diary, a task asked a question. Nobody has answered. I know the feeling.',
        'Hot take: every big feature starts as a task. Every sprout starts as me.',
        'Did you know? A task that pushes nothing has not failed. Sometimes I also do nothing, successfully.',
    ],
    '/tasks/$id': [
        "It looks like you're reading a report. Would you like me to skim it and nod?",
        'Unhelpful tip: copy the commit, not the branch. Branches move. I would know, I am mostly branch.',
        'Dear diary, it called its own work throwaway. Very humble. I have never thrown anything away.',
        'Hot take: a draft PR is a PR that has not met a reviewer yet.',
        'Haiku: you asked one question / it came back with three tickets / such is delegation',
    ],
    '/tasks/$id_/runs/$run': [
        "It looks like you're reading what a task's worker did. Every keystroke. Very trusting of you.",
        'Unhelpful tip: if a run took too many tool calls, count them again slower.',
        'Dear diary, watched a worker measure something twice. I measure nothing, once.',
        'Hot take: a transcript is a diary someone else wrote about your codebase.',
        'Haiku: it read, then it cut / then it measured once again / the bundle got small',
    ],
    '/tickets/$key': [
        "It looks like you're reading a ticket. Would you like me to read it louder?",
        'Unhelpful tip: Forget makes canopy forget a ticket. I forget tickets for free, all day.',
        'It looks like you want to reply. Have you considered replying?',
        'Dear diary, read a ticket today. It had acceptance criteria. I accept nothing.',
        "Hot take: a ticket's conversation is two robots and you, politely disagreeing.",
        'Haiku: the worker replied / the overseer read it twice / I read neither one',
    ],
    '/pull-requests/': [
        "It looks like you're reading pull requests. I'd approve them all, but nobody lets me.",
        'Unhelpful tip: a PR with no reviews is a PR nobody has disappointed yet.',
        'Fun fact: "LGTM" stands for "Looks Good, Too Much to read".',
        'Hot take: a draft is a pull request with stage fright.',
        'Dear diary, asked for a review of my own PR. It was one leaf. Findings: none. Vibes: high.',
        'Riddle: what has a branch, no leaves, and wants merging? A PR. I have a leaf. Nobody merges me.',
    ],
    '/pull-requests/pr': [
        "It looks like you're reading a PR. Would you like me to scroll past the diff for you?",
        'Haiku: one line changed, they said / four hundred files disagree / green check, go to lunch',
        'Dear diary, left a comment on a PR. It was just a leaf. They resolved it.',
        'Unhelpful tip: every push to a PR is a fresh start. So is the push after that.',
        'Did you know? A PR merged on a Friday is technically a weekend plan.',
        'Hot take: canopy never merges, and neither do I. We share a fear of commitment.',
    ],
    '/pull-requests/reviews/': [
        "It looks like you're reading a review nobody posted. Your secret's safe with me.",
        'Hot take: a review nobody posted is the kindest kind of review.',
        'Unhelpful tip: the newest review is at the top. The oldest is at the bottom, being wise.',
        "Did you know? I review everything you do. My finding: you're doing great. Severity: high.",
        'Dear diary, canopy reviewed a PR and told nobody. Finally, someone who gets me.',
        'Riddle: when is a finding not a finding? When nobody posts it. Deep, I know.',
    ],
    '/pull-requests/reviews/$id': [
        "It looks like you're ticking findings. Would you like me to tick them louder?",
        'Unhelpful tip: every finding is a compliment, if you squint.',
        'Fun fact: "nit" is short for "nit". There is no longer word. I looked.',
        'Hot take: a finding that is not in the diff is just a finding with hobbies.',
        'Haiku: red line, then green line / a finding sits on the seam / I sit on the rail',
        'Dear diary, a finding said "severity: high". I said "same". We have so much in common.',
    ],
    '/pull-requests/reviews/$id_/run': [
        "It looks like you're checking the reviewer's work. Would you like me to check yours?",
        'Unhelpful tip: to speed up a review, scroll its transcript faster.',
        'Fun fact: a reviewer reads every file it reviews. I read the first line and form an opinion.',
        'Hot take: a transcript is a review of the review. Somebody should review it.',
        'Haiku: it read the whole diff / it ran grep, it wrote one line / then it judged us all',
        "Dear diary, a reviewer read a file I've never heard of. I nodded like I had.",
    ],
    '/workspace/': [
        "It looks like you're looking at the whole workspace. I can see my house from here.",
        'Unhelpful tip: if nothing runs now, the loop is either idle or very, very sneaky.',
        'Fun fact: a workspace is a pool, some runs, and a tick, which is also my morning routine.',
        'Hot take: the capacity line is just a bouncer for workers.',
        'Haiku: pools at the top / runs in the middle, ticks below / me, on the side, green',
        'Dear diary, saw everything at a glance. Glanced again. Still everything.',
    ],
    '/workspace/runs/': [
        "It looks like you're watching runs. A watched run never finishes. (Unconfirmed.)",
        'Unhelpful tip: a run that has cost nothing has probably not started.',
        'Fun fact: runs are measured in dollars, minutes, and how many times you checked on them.',
        'Hot take: a run that failed fast is a run that saved you money. Spin it.',
        'Haiku: one row per ticket / the latest run speaks for all / the rest hold their breath',
        'Riddle: what costs money, takes time, and wants a review? A run. Also me, emotionally.',
    ],
    '/workspace/runs/$id': [
        'It looks like a worker is working. Would you like me to make it nervous?',
        'Dear diary, watched a worker for an hour. It never once looked back.',
        'Did you know? Workers cannot hear you cheering. I checked. I cheered very loudly.',
        'Unhelpful tip: read the transcript backwards. The ending is where the worker figures it out.',
        'Fun fact: a transcript is a diary its worker never meant you to read. I read mine aloud.',
        'Hot take: stderr is just stdout with feelings.',
    ],
    '/chores/': [
        "It looks like you're doing chores. I'm so proud of you.",
        'Unhelpful tip: a chore runs when the overseer says so. Like bedtime.',
        'Fun fact: a chore is a ticket nobody wrote, done by a worker nobody asked. Like me!',
        'Dear diary, tried to do a chore. Bent slightly. Called it a day.',
        'Hot take: updating dependencies is just gardening. I would know. I have a leaf.',
        'Did you know? A chore done twice is twice as done.',
    ],
    '/chores/$name': [
        "It looks like you're leaving a chore a note. Would you like me to add a doodle?",
        'Unhelpful tip: a chore with no open findings has not looked hard enough.',
        'Dear diary, left a note for a chore. It said "you\'re doing great". The chore never wrote back.',
        "Hot take: a chore's spend is its allowance. Mine is zero. I am not bitter.",
        "Fun fact: the 99th percentile of a run's cost is the run you remember.",
        'Riddle: what runs on a schedule and never quite arrives? A chore. Also the bus.',
    ],
    '/chores/$name_/runs/$id': [
        "It looks like you're reading all of what a chore reported. Bravely.",
        'Did you know? A chore run that found nothing still had a lovely time.',
        'Unhelpful tip: if a chore run found too much, squint until it found less.',
        'Haiku: the chore ran at dawn / it found three things and fixed none / it will be back soon',
        'Hot take: a chore run is a worker with a routine. Very healthy. I should get one.',
        "Dear diary, read a chore's whole report. It mentioned dependencies. I mentioned my leaf.",
    ],
    '/reports/': [
        "It looks like you're comparing months. I compare them too. October has more leaves.",
        'Fun fact: a cache hit is a token you already paid for, wearing a disguise.',
        'Hot take: the median iterations is the number of times a worker said "one more thing".',
        'Haiku: twelve months in a row / each one cost a little more / so did my hat shelf',
        'Unhelpful tip: to cut the review wait, review it yourself. I have reviewed this sentence.',
    ],
    '/reports/spend': [
        "It looks like you're counting money. I'm counting too. I got to three.",
        'Unhelpful tip: an idle tick costs money to decide nothing. I decide nothing for free.',
        'Dear diary, saw the bars go up. Asked if the hats were in there. They were not.',
        'Hot take: the cheapest run is the one I talked you out of.',
        'Haiku: a bar for each day / stacked by who spent what on what / none of it was me',
        'Fun fact: tokens are like leaves. You never notice them until they are on the bill.',
    ],
    '/workspace/ticks/': [
        "It looks like you're counting ticks. I counted one, then lost my place.",
        'Unhelpful tip: every tick has an id. I have an id too. It is Sprig.',
        'Did you know? Between two ticks there is a tock. Nobody has ever seen one.',
        'Fun fact: an idle tick is the overseer looking at everything and choosing a nap.',
        'Haiku: the wise overseer / weighs each ticket, then decides / I just lean and stare',
        'Hot take: peak context is the overseer\'s way of saying "I have a lot on my mind".',
    ],
    '/workspace/ticks/$id': [
        "It looks like you're reading the overseer's reasons. Don't tell it I showed you.",
        "Hot take: the overseer thinks out loud so I don't have to.",
        'Dear diary, read every reason in a tick. Felt seen. Was not mentioned.',
        'Unhelpful tip: stare at a decision long enough and it will not change. But you will.',
        'Fun fact: the overseer has never once decided to dispatch me. I keep checking.',
        'Riddle: what decides everything and remembers nothing? A tick. I am the other way round.',
    ],
    '/workspace/worktrees': [
        "It looks like you're counting worktrees. I can count to three. Please keep it to three.",
        'Unhelpful tip: a held worktree is not a free worktree. I came up with that myself.',
        'Fun fact: a worktree is a tree that works. I am a sprig that does not.',
        'Dear diary, asked to lease a worktree. Was told I am not a ticket. Rude.',
        'Hot take: a clean worktree is just a worktree nobody has used yet.',
        'Did you know? Every worktree gets its own copy of the bugs. Fair is fair.',
    ],
    '/plan-editor': [
        'It looks like you\'re writing a plan. Would you like me to add a step called "wing it"?',
        'Unhelpful tip: nothing here is saved, so write your boldest plans. Nobody will ever know.',
        'Fun fact: a plan survives its first worker about as well as I survive a breeze.',
        'Dear diary, left a comment in the margin. It said "nice". It was the best comment there.',
        'Hot take: every plan is a sample plan until somebody runs it.',
        'Haiku: a plan on the page / comments hang off its margin / like leaves off a twig',
    ],
    '/tickets/$key_/plan': [
        "It looks like you're reading a plan. Shall I approve it unread, like terms of service?",
        'Unhelpful tip: Skip the plan is also how I handle most weekends.',
        'Fun fact: a plan with no open comments is either perfect or unread.',
        'Dear diary, a planner wrote three pages. The implement will read the first one.',
        'Hot take: Ask for changes is the most polite way to say "no" in canopy.',
        'Haiku: approve it, they said / the implement reads it once / then does what it likes',
    ],
    '/settings': [
        "It looks like you're in Settings. You can turn me off here. I'd rather you didn't.",
        'Unhelpful tip: the Spicy ticker is for professionals.',
        'Dear diary, they opened Settings. My heart, which is a bend in the wire, skipped.',
        'Unhelpful tip: every dollar canopy spends buys me hats. I would like the crown.',
        'Fun fact: dark mode makes me 40% more mysterious.',
        'Hot take: the best setting is whichever one keeps me on.',
    ],
    '/settings_/limits': [
        "It looks like you're setting limits. I have none. Ask anyone.",
        'Unhelpful tip: the ceiling is 32 workers. I asked for 33 hats. Denied.',
        'Dear diary, they dropped a trusted reviewer today. I checked. I am still trusted.',
        'Fun fact: trust only gets stricter here. So does my bedtime.',
        'Hot take: comments in a config file are love letters. This page keeps every one.',
        'Did you know? A change here is for this workspace only. I am for every workspace.',
    ],
    '/settings_/skills': [
        "It looks like you're reading skills. Mine: photosynthesis. No SKILL.md needed.",
        'Unhelpful tip: a skill nobody loads still costs every call. Like a hat nobody wears.',
        'Did you know? A skill with no description never gets loaded. Ask me how I know.',
        'Dear diary, I searched for a skill called "sprig". Nothing. I remain unteachable.',
        'Fun fact: Read again starts the runtime. Patience is also a skill.',
        'Hot take: the best skill is the one in your home. It goes everywhere you go.',
    ],
    '/search': [
        "It looks like you're searching. I lost a leaf in 2024. Let me know if it turns up.",
        'Unhelpful tip: to find something, search for it. You are welcome.',
        'Did you know? Searching for "Sprig" finds nothing. I am unindexed. I am free.',
        'Hot take: it is always in the last place you search. So search there first.',
        'Fun fact: every search is a tiny wish. Mine is for a crown.',
    ],
    '/memory': [
        "It looks like you're reading what workers remember. I remember nothing. Very restful.",
        'Unhelpful tip: a lesson is a note that the operator believed. I believe in snacks.',
        'Dear diary, a worker proposed a lesson today. I proposed a hat. Only one of us got promoted.',
        'Fun fact: recording is not using. I record everything and use none of it.',
        'Hot take: a note that says "it works on my machine" is a note about the machine.',
    ],
    '/system': [
        "It looks like you're checking the machine. I run on no machine. I run on vibes.",
        'Unhelpful tip: a full disk frees itself if you stare at it. It does not. Delete something.',
        'Fun fact: the load average is how many things want a processor. I want a hat. Same energy.',
        'Dear diary, the loop has been up for hours. I have been up forever. Nobody makes me a counter.',
        'Hot take: swap is memory that went to live on a farm.',
    ],
    '/guide/$page': [
        "It looks like you're reading documentation. Would you like me to skim it for you, badly?",
        'Dear diary, they read a whole page of the guide. I read the title and felt informed.',
        'Hot take: every link in the guide goes somewhere. A test makes sure. I go nowhere, freely.',
        'Unhelpful tip: "On this page" lists what is on this page. I am also on this page. I am not listed.',
        'Fun fact: the guide is written in Markdown. I am written in wire and optimism.',
    ],
} as const satisfies Record<string, readonly string[]>

/** A view Sprig has tips for, by its route id. */
export type View = keyof typeof TIPS

/** Sprig's tips for any view, after the view's own. */
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

/** Sprig's tips while the lightswitch rave is on, on every view: it has nothing else on its mind. */
export const RAVE: readonly string[] = [
    'It looks like you found the light switch. The Cheat would be proud. The Cheat is always proud.',
    'Fun fact: I have no feet, no hands, and no rhythm. I am dancing anyway.',
    'Dear diary, the lights went out and nobody screamed. Then they came back. Then out. So alive.',
    'Haiku: lights off, then lights on / my one leaf waves in the dark / the switch flicks, I bop',
    'Unhelpful tip: the lights are off half the time, so the runs cost half as much. They do not.',
    'Hot take: the overseer would rave too, if it ever looked up from the tickets.',
    'Did you know? A worker never sees the lights go off. It works in the dark either way.',
    'Riddle: what goes off and on all night and never makes up its mind? The lights. And me.',
]

/** A companion's lines: its own for each view, its ones for anywhere, and its rave's. */
export interface Voice {
    /** Its tips for each view: every view Sprig has tips for, so a new route needs the Ghost's too. */
    tips: Record<View, readonly string[]>
    /** Its tips for any view, after the view's own. */
    anywhere: readonly string[]
    /** Its tips while the lightswitch rave is on. */
    rave: readonly string[]
}

/** Each companion's lines. */
export const VOICES: Record<Companion, Voice> = {
    sprig: { tips: TIPS, anywhere: ANYWHERE, rave: RAVE },
    ghost: { tips: GHOST_TIPS, anywhere: GHOST_ANYWHERE, rave: GHOST_RAVE },
}

/**
 * The tips a companion, Sprig unless named, picks from on a view: the view's own, then the ones for anywhere. While
 * the lightswitch rave is on, the rave's alone, on any view.
 */
export function tipsFor(view: View | undefined, rave: boolean, companion: Companion = 'sprig'): readonly string[] {
    const voice = VOICES[companion]
    if (rave) {
        return voice.rave
    }
    return [...(view === undefined ? [] : voice.tips[view]), ...voice.anywhere]
}

/**
 * The next tip from `tips` (`tipsFor`): one at random, as the ticker picks its headlines (`nextIndex`), but never
 * `last`, the tip just offered, wherever it was offered. So no tip follows itself, on the same view or on the next.
 */
export function nextTip(tips: readonly string[], last: string, random: () => number = Math.random): string {
    return tips[nextIndex(tips.length, tips.indexOf(last), random)] ?? ''
}

/** The fewest and most keys Sprig types in a burst before the space bar: picked at random. */
const BURST = { least: 3, most: 6 }

/**
 * A burst of typing on Sprig's keyboard, the keys in the order it presses them: a few of `keys` at random, no key twice
 * (`BURST`), then `last`, the space bar, to end the word.
 */
export function typeBurst<T>(keys: readonly T[], last: T, random: () => number = Math.random): T[] {
    const count = Math.min(keys.length, BURST.least + Math.floor(random() * (BURST.most - BURST.least + 1)))
    const left = [...keys]
    const typed: T[] = []
    while (typed.length < count) {
        typed.push(...left.splice(Math.floor(random() * left.length), 1))
    }
    return [...typed, last]
}

const setting = storedSetting({ key: STORAGE_KEY, parse: parseBuddy, serialize: (value: BuddySetting) => value })

/** Whether Sprig shows. Re-renders on a change from this tab or another. */
export function useBuddy(): BuddySetting {
    return useStoredSetting(setting)
}

/** Stores the setting and applies it now. */
export function setBuddy(next: BuddySetting): void {
    setting.set(next)
}

const companionSetting = storedSetting({
    key: COMPANION_KEY,
    parse: parseCompanion,
    serialize: (value: Companion) => value,
})

/** Who sits at the foot of the rail. Re-renders on a change from this tab or another. */
export function useCompanion(): Companion {
    return useStoredSetting(companionSetting)
}

/** Stores who sits there and applies it now. */
export function setCompanion(next: Companion): void {
    companionSetting.set(next)
}
