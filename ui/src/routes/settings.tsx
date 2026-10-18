import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { createFileRoute } from '@tanstack/react-router'
import { LogOut, Megaphone, Monitor, Moon, RefreshCw, Sun } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { useState } from 'react'

import { reloadConfig, setNotice, showLoop, signOut } from '@/api/mutations'
import { keys, sessionQuery, spendQuery } from '@/api/queries'
import { Cost } from '@/components/cost'
import { Disclosure } from '@/components/disclosure'
import { HatPreview } from '@/components/hat'
import { Input, Textarea } from '@/components/input'
import { Notice } from '@/components/notice'
import { PageHeader, Panel, PanelHeader } from '@/components/panel'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Collapsible, CollapsibleContent } from '@/components/ui/collapsible'
import { Skeleton } from '@/components/ui/skeleton'
import { Switch } from '@/components/ui/switch'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import { setBuddy, useBuddy } from '@/lib/buddy'
import { costText } from '@/lib/cost-total'
import { balanceCents, buy, HATS, setWardrobe, useWardrobe } from '@/lib/hats'
import type { Hat } from '@/lib/hats'
import type { TickerTopic } from '@/lib/headlines'
import { noticeSetText, reloadedText } from '@/lib/outcomes'
import { setRave, useRave } from '@/lib/rave'
import { dropDrafts } from '@/lib/reply-draft'
import { setSendKey, useSendKey } from '@/lib/send-key'
import type { SendKey } from '@/lib/send-key'
import { clampGap, MAX_GAP, setTickerSettings, useTickerSettings, withTopic } from '@/lib/ticker-settings'
import type { TickerSpeed } from '@/lib/ticker-settings'
import { setToastSettings, TOAST_STATES, useToastSettings, withState } from '@/lib/toast-settings'
import type { ToastSubject } from '@/lib/toast-settings'
import { readable } from '@/lib/words'
import type { ThemePreference } from '@/theme/store'
import { switchTheme } from '@/theme/transition'
import { useTheme } from '@/theme/use-theme'

/**
 * What this browser keeps (the theme, the send key, the toasts, the fun, the session), and reloading the loop's config.
 */
export const Route = createFileRoute('/settings')({
    component: SettingsPage,
})

const THEMES: { value: ThemePreference; label: string; icon: LucideIcon }[] = [
    { value: 'light', label: 'Light', icon: Sun },
    { value: 'dark', label: 'Dark', icon: Moon },
    { value: 'system', label: 'System', icon: Monitor },
]

const SPEEDS: { value: TickerSpeed; label: string }[] = [
    { value: 'slow', label: 'Slow' },
    { value: 'normal', label: 'Normal' },
    { value: 'spicy', label: 'Spicy' },
]

const TOPICS: { value: TickerTopic; label: string }[] = [
    { value: 'programming', label: 'Programming' },
    { value: 'vibes', label: 'Vibe coding' },
    { value: 'tips', label: 'Tips' },
]

// How long a notice set here lasts; `canopy notice --for` takes any duration up to a week.
const LASTS: { value: string; label: string; minutes: number }[] = [
    { value: '1h', label: '1 hour', minutes: 60 },
    { value: '4h', label: '4 hours', minutes: 240 },
    { value: '1d', label: '1 day', minutes: 1440 },
]

const SEND_KEYS: { value: SendKey; label: string }[] = [
    { value: 'enter', label: 'Enter' },
    { value: 'mod-enter', label: 'Ctrl+Enter' },
    { value: 'button', label: 'Button only' },
]

function SettingsPage() {
    const { preference } = useTheme()
    return (
        <>
            <PageHeader title="Settings">
                The theme, the send key, the toasts, and the fun are kept in this browser. Everything else canopy reads
                from its config files.
            </PageHeader>
            <Panel>
                <PanelHeader label="Theme" />
                <div className="flex items-center justify-between gap-4 p-3">
                    <p className="text-sm text-muted-foreground">
                        Follows the system unless you pick one. Syncs across tabs.
                    </p>
                    {/* Switched on click, not on a value change, so the transition grows from the item pressed. */}
                    <ToggleGroup type="single" value={preference} aria-label="Theme">
                        {THEMES.map(({ value, label, icon: Icon }) => (
                            <ToggleGroupItem
                                key={value}
                                value={value}
                                data-testid={`theme-${value}`}
                                onClick={(event) => switchTheme(value, event.currentTarget)}
                            >
                                <Icon />
                                {label}
                            </ToggleGroupItem>
                        ))}
                    </ToggleGroup>
                </div>
            </Panel>
            <SendKeyPanel />
            <ToastsPanel />
            <NoticePanel />
            <ConfigPanel />
            {/* Second to last: below what changes how canopy works, above signing out. */}
            <FunPanel />
            <SessionPanel />
        </>
    )
}

/**
 * The fun, in one place: an on/off for the ticker and for Sprig, then the ticker's pace, the pause between its
 * headlines, and the topics they are drawn from. Its header hides a light switch.
 */
function FunPanel() {
    const { on, speed, gap, hidden } = useTickerSettings()
    const buddy = useBuddy()
    return (
        <Panel>
            <PanelHeader label="Fun">
                <LightSwitch />
            </PanelHeader>
            <div className="flex items-center justify-between gap-4 border-b p-3">
                <p id="fun-items" className="text-sm text-muted-foreground">
                    The ticker crawls joke headlines across the header. Sprig, at the foot of the side rail, has a tip
                    for every page; none of them help. Each sits out a window with no room for it.
                </p>
                <fieldset aria-labelledby="fun-items" className="flex shrink-0 items-center gap-4">
                    <label htmlFor="fun-ticker" className="inline-flex items-center gap-2 text-xs whitespace-nowrap">
                        <Checkbox
                            id="fun-ticker"
                            checked={on}
                            data-testid="fun-ticker"
                            onCheckedChange={(checked) => setTickerSettings({ on: checked === true })}
                        />
                        Ticker
                    </label>
                    <label htmlFor="fun-sprig" className="inline-flex items-center gap-2 text-xs whitespace-nowrap">
                        <Checkbox
                            id="fun-sprig"
                            checked={buddy === 'on'}
                            data-testid="fun-sprig"
                            onCheckedChange={(checked) => setBuddy(checked === true ? 'on' : 'off')}
                        />
                        Sprig
                    </label>
                </fieldset>
            </div>
            <div className="flex items-center justify-between gap-4 border-b p-3">
                <p className="text-sm text-muted-foreground">
                    How fast the ticker&apos;s headlines crawl, one at a time.
                </p>
                <ToggleGroup
                    type="single"
                    value={speed}
                    aria-label="Ticker speed"
                    disabled={!on}
                    onValueChange={(value) => {
                        const picked = SPEEDS.find((s) => s.value === value)
                        if (picked) {
                            setTickerSettings({ speed: picked.value })
                        }
                    }}
                >
                    {SPEEDS.map(({ value, label }) => (
                        <ToggleGroupItem key={value} value={value} data-testid={`ticker-${value}`}>
                            {label}
                        </ToggleGroupItem>
                    ))}
                </ToggleGroup>
            </div>
            <div className="flex items-center justify-between gap-4 border-b p-3">
                <label htmlFor="ticker-gap" className="text-sm text-muted-foreground">
                    Seconds the ticker stays empty between one headline and the next.
                </label>
                <span className="inline-flex items-center gap-2">
                    <Input
                        id="ticker-gap"
                        type="number"
                        inputMode="numeric"
                        min={0}
                        max={MAX_GAP}
                        step={1}
                        defaultValue={gap}
                        disabled={!on}
                        className="readout w-20 text-right"
                        data-testid="ticker-gap"
                        onChange={(event) => {
                            const value = event.currentTarget.value
                            const seconds = value === '' ? undefined : clampGap(Number(value))
                            if (seconds !== undefined) {
                                setTickerSettings({ gap: seconds })
                            }
                        }}
                        onBlur={(event) => {
                            // Shows what was kept: an empty or out-of-range entry snaps back to the stored value.
                            const value = event.currentTarget.value
                            event.currentTarget.value = String(value === '' ? gap : (clampGap(Number(value)) ?? gap))
                        }}
                    />
                    <span className="readout text-xs text-muted-foreground">s</span>
                </span>
            </div>
            <div className="flex items-center justify-between gap-4 p-3">
                <p id="ticker-topics" className="text-sm text-muted-foreground">
                    Which headlines the ticker shows. Tips about canopy are mixed in with the jokes.
                </p>
                <fieldset aria-labelledby="ticker-topics" className="flex shrink-0 items-center gap-4">
                    {TOPICS.map(({ value, label }) => (
                        <label key={value} className="inline-flex items-center gap-2 text-xs whitespace-nowrap">
                            <Checkbox
                                checked={!hidden.includes(value)}
                                disabled={!on}
                                data-testid={`ticker-topic-${value}`}
                                onCheckedChange={(checked) =>
                                    setTickerSettings({ hidden: withTopic(hidden, value, checked === true) })
                                }
                            />
                            {label}
                        </label>
                    ))}
                </fieldset>
            </div>
            <HatShop />
        </Panel>
    )
}

/**
 * An Easter egg at the end of the Fun panel's header, with no words beside it: The Cheat's light switch. Flipped, it
 * starts the lightswitch rave over the whole app (`Rave` in src/components/shell/rave.tsx), its lever flicking with
 * the lights; flipped back, it ends it.
 */
function LightSwitch() {
    const rave = useRave()
    return (
        <Switch
            aria-label="Lightswitch rave"
            title="The Cheat's light switch"
            checked={rave === 'on'}
            data-testid="light-switch"
            className="*:data-[state=checked]:rave-flick"
            onCheckedChange={(checked) => setRave(checked ? 'on' : 'off')}
        />
    )
}

/**
 * Sprig's hat shop, the last of the Fun panel's details, folded under its wallet until opened. The wallet is
 * everything canopy has spent, as `GET /api/spend` totals it, less every hat bought: each dollar the agent runtime
 * reports is a dollar for hats. A hat bought goes on at once; one owned goes on or comes off with a click. All sales
 * are final.
 */
function HatShop() {
    const total = useQuery(spendQuery).data?.total_usd
    const loaded = total !== undefined
    const wardrobe = useWardrobe()
    const left = balanceCents(total, wardrobe.owned)
    // Folded until asked for: eight hats are a lot of Settings for something most visits leave alone.
    const [open, setOpen] = useState(false)
    return (
        <Collapsible asChild open={open} onOpenChange={setOpen}>
            <div className="border-t" data-testid="hats">
                <div className="flex items-center justify-between gap-4 p-3">
                    <p className="text-sm text-muted-foreground">
                        Every dollar canopy spends is a dollar for Sprig&apos;s hats. Sprig wears the one you pick while
                        it is on. All sales are final.
                    </p>
                    <div className="flex shrink-0 flex-col items-end" data-testid="hats-wallet">
                        {loaded ? (
                            <Cost usd={left / 100} className="text-sm text-foreground" />
                        ) : (
                            <Skeleton className="h-5 w-14" />
                        )}
                        <span className="text-2xs text-muted-foreground">
                            left of {loaded ? <Cost usd={total} /> : '…'} spent
                        </span>
                    </div>
                    <Disclosure open={open} what="hats" data-testid="hats-toggle" />
                </div>
                <CollapsibleContent asChild>
                    <ul className="grid grid-cols-2 gap-2 border-t p-3 sm:grid-cols-4">
                        {HATS.map((hat) => (
                            <HatItem
                                key={hat.id}
                                hat={hat}
                                owned={wardrobe.owned.includes(hat.id)}
                                worn={wardrobe.worn === hat.id}
                                shortCents={loaded ? Math.max(0, hat.price * 100 - left) : undefined}
                                onBuy={() => {
                                    const next = buy(wardrobe, hat.id, total)
                                    if (next) {
                                        setWardrobe(next)
                                    }
                                }}
                                onWear={(on) => setWardrobe({ ...wardrobe, worn: on ? hat.id : null })}
                            />
                        ))}
                    </ul>
                </CollapsibleContent>
            </div>
        </Collapsible>
    )
}

/** One hat in the shop: what it looks like and costs, and Buy, or Wear and Take off once owned. */
function HatItem({
    hat,
    owned,
    worn,
    shortCents,
    onBuy,
    onWear,
}: {
    hat: Hat
    owned: boolean
    worn: boolean
    shortCents: number | undefined
    onBuy: () => void
    onWear: (on: boolean) => void
}) {
    return (
        <li
            className="flex flex-col items-center gap-1 rounded-md border p-2 text-center"
            data-testid={`hat-${hat.id}`}
        >
            <HatPreview id={hat.id} className="h-10 w-12" />
            <span className="text-xs text-foreground">{hat.name}</span>
            <span className="grow text-2xs text-muted-foreground">{hat.blurb}</span>
            {owned ? (
                <Button
                    variant={worn ? 'secondary' : 'outline'}
                    size="xs"
                    onClick={() => onWear(!worn)}
                    data-testid={`hat-${hat.id}-wear`}
                >
                    {worn ? 'Take off' : 'Wear'}
                </Button>
            ) : (
                <Button
                    variant="outline"
                    size="xs"
                    disabled={shortCents !== 0}
                    title={
                        shortCents !== undefined && shortCents > 0 ? `${costText(shortCents / 100)} short` : undefined
                    }
                    onClick={onBuy}
                    data-testid={`hat-${hat.id}-buy`}
                >
                    Buy <Cost usd={hat.price} />
                </Button>
            )}
        </li>
    )
}

/** Which key sends a reply or a note. */
function SendKeyPanel() {
    const sendKey = useSendKey()
    return (
        <Panel>
            <PanelHeader label="Replies" />
            <div className="flex items-center justify-between gap-4 p-3">
                <p className="text-sm text-muted-foreground">
                    Which key sends a reply or a note. Shift+Enter always makes a new line. Ctrl+Enter is ⌘+Enter on a
                    Mac.
                </p>
                <ToggleGroup
                    type="single"
                    value={sendKey}
                    aria-label="Send a reply with"
                    className="shrink-0"
                    onValueChange={(value) => {
                        const picked = SEND_KEYS.find((k) => k.value === value)
                        if (picked) {
                            setSendKey(picked.value)
                        }
                    }}
                >
                    {SEND_KEYS.map(({ value, label }) => (
                        <ToggleGroupItem key={value} value={value} data-testid={`send-key-${value}`}>
                            {label}
                        </ToggleGroupItem>
                    ))}
                </ToggleGroup>
            </div>
        </Panel>
    )
}

// What each subject's row on the Toasts panel says, in TOAST_STATES order: a subject added there needs one here.
const TOAST_ROWS: Record<ToastSubject, { label: string; text: string }> = {
    tickets: {
        label: 'Tickets',
        text: 'When a ticket moves into a state checked here. Its PRs have phases of their own, which these leave out.',
    },
}

/**
 * Which changes show a toast, on whatever page is open: a row for each subject, with a checkbox for each of its states.
 * None until the operator checks one.
 */
function ToastsPanel() {
    const settings = useToastSettings()
    return (
        <Panel>
            <PanelHeader label="Toasts" />
            <div className="divide-y">
                {(Object.keys(TOAST_ROWS) as ToastSubject[]).map((subject) => (
                    <div key={subject} className="flex flex-col gap-2 p-3">
                        <p id={`toasts-${subject}`} className="text-sm text-muted-foreground">
                            <span className="text-foreground">{TOAST_ROWS[subject].label}</span>:{' '}
                            {TOAST_ROWS[subject].text}
                        </p>
                        <fieldset
                            aria-labelledby={`toasts-${subject}`}
                            className="flex flex-wrap items-center gap-x-4 gap-y-2"
                        >
                            {TOAST_STATES[subject].map((state) => (
                                <label
                                    key={state}
                                    className="inline-flex items-center gap-2 font-mono text-xs whitespace-nowrap"
                                >
                                    <Checkbox
                                        checked={settings[subject].includes(state)}
                                        data-testid={`toast-${subject}-${state}`}
                                        onCheckedChange={(checked) =>
                                            setToastSettings(withState(settings, subject, state, checked === true))
                                        }
                                    />
                                    {readable(state)}
                                </label>
                            ))}
                        </fieldset>
                    </div>
                ))}
            </div>
        </Panel>
    )
}

/**
 * Sets the operator's notice to workers, as `canopy notice TEXT --for DURATION` does (docs/design §8): every run
 * dispatched until it lapses hears it. The banner above every page shows it while it is in force, and clears it.
 */
function NoticePanel() {
    const client = useQueryClient()
    const [text, setText] = useState('')
    const [lasts, setLasts] = useState('4h')
    const minutes = LASTS.find((l) => l.value === lasts)?.minutes ?? 240
    const mutation = useMutation({
        mutationFn: () => setNotice(text, minutes),
        onSuccess: (changed) => {
            showLoop(client, changed.loop)
            setText('')
        },
    })
    return (
        <Panel>
            <PanelHeader label="Notice to workers" />
            <form
                className="flex flex-col gap-2 p-3"
                onSubmit={(event) => {
                    event.preventDefault()
                    mutation.mutate()
                }}
            >
                <p className="text-sm text-muted-foreground">
                    Tell every run dispatched from now on about something passing outside the work, such as a CI outage,
                    as <code className="font-mono text-xs">canopy notice</code> does. Workers, reviews, and chores hear
                    it, and the overseer holds a failed check it explains. It lapses on its own; setting another
                    replaces it. A run already running keeps the prompt it started with.
                </p>
                <Textarea
                    value={text}
                    onChange={(event) => setText(event.target.value)}
                    placeholder="Artifactory is down: CI builds that fetch dependencies will likely fail."
                    aria-label="Notice to workers"
                    data-testid="notice-text"
                    className="min-h-16"
                />
                <div className="flex flex-wrap items-center justify-between gap-2">
                    <ToggleGroup
                        type="single"
                        value={lasts}
                        aria-label="Lasts for"
                        onValueChange={(value) => {
                            if (value !== '') {
                                setLasts(value)
                            }
                        }}
                    >
                        {LASTS.map(({ value, label }) => (
                            <ToggleGroupItem key={value} value={value} data-testid={`notice-lasts-${value}`}>
                                {label}
                            </ToggleGroupItem>
                        ))}
                    </ToggleGroup>
                    <Button
                        type="submit"
                        variant="outline"
                        disabled={mutation.isPending || text.trim() === ''}
                        data-testid="notice-set"
                    >
                        <Megaphone />
                        Set notice
                    </Button>
                </div>
                <Notice error={mutation.error}>{mutation.data ? noticeSetText(mutation.data) : null}</Notice>
            </form>
        </Panel>
    )
}

/** Asks the loop to read its config files again, as SIGHUP does. A tick running then finishes on the config it had. */
function ConfigPanel() {
    const mutation = useMutation({ mutationFn: reloadConfig })
    return (
        <Panel>
            <PanelHeader label="Config" />
            <div className="flex items-center justify-between gap-4 p-3">
                <div className="flex flex-col gap-1">
                    <p className="text-sm text-muted-foreground">
                        The loop reads the workspace file and your{' '}
                        <code className="font-mono text-xs">config.toml</code> when it starts. Reload reads them again,
                        as <code className="font-mono text-xs">kill -HUP</code> does; a running tick finishes first. A
                        file that does not load changes nothing.
                    </p>
                    {/* A config error names its file and key, a line each. */}
                    <Notice error={mutation.error} className="whitespace-pre-line">
                        {mutation.data ? reloadedText(mutation.data) : null}
                    </Notice>
                </div>
                <Button
                    variant="outline"
                    onClick={() => mutation.mutate()}
                    disabled={mutation.isPending}
                    data-testid="config-reload"
                >
                    <RefreshCw />
                    Reload
                </Button>
            </div>
        </Panel>
    )
}

/** Signs this browser out. Every browser is signed out by a new secret: `canopy secret --rotate`, then a restart. */
function SessionPanel() {
    const client = useQueryClient()
    const { data } = useQuery(sessionQuery)
    const mutation = useMutation({
        mutationKey: keys.session,
        mutationFn: signOut,
        onSuccess: (session) => {
            dropDrafts()
            client.setQueryData(keys.session, session)
            client.removeQueries({ predicate: (query) => query.queryKey[0] !== 'session' })
        },
    })
    // Mock data served without a secret has no session to end.
    if (data?.token === 'open') {
        return null
    }
    return (
        <Panel>
            <PanelHeader label="Session" />
            <div className="flex items-center justify-between gap-4 p-3">
                <div className="flex flex-col gap-1">
                    <p className="text-sm text-muted-foreground">
                        Signed in with the listener secret for 30 days. To sign every browser out, run{' '}
                        <code className="font-mono text-xs">canopy secret --rotate</code> and restart the loop.
                    </p>
                    <Notice error={mutation.error} />
                </div>
                <Button variant="outline" onClick={() => mutation.mutate()} disabled={mutation.isPending}>
                    <LogOut />
                    Sign out
                </Button>
            </div>
        </Panel>
    )
}
