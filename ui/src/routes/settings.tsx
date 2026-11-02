import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { createFileRoute, Link } from '@tanstack/react-router'
import { ChevronRight, LogOut, Monitor, Moon, RefreshCw, Sun } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { useState } from 'react'
import type { ReactNode } from 'react'

import { reloadConfig, signOut } from '@/api/mutations'
import { keys, personasQuery, sessionQuery, spendQuery } from '@/api/queries'
import { Code } from '@/components/code'
import { ConfigModels } from '@/components/config-models'
import { Cost } from '@/components/cost'
import { Disclosure } from '@/components/disclosure'
import { ShellPreview } from '@/components/ghost-shell'
import { HatPreview } from '@/components/hat'
import { Input } from '@/components/input'
import { Notice } from '@/components/notice'
import { NoticeForm } from '@/components/notice-form'
import { PageHeader, Panel, PanelHeader } from '@/components/panel'
import { PersonasMenu } from '@/components/personas-menu'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { Collapsible, CollapsibleContent } from '@/components/ui/collapsible'
import { Skeleton } from '@/components/ui/skeleton'
import { Switch } from '@/components/ui/switch'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import { setFindingsHidden, useFindingsHidden } from '@/lib/attention-findings'
import { NAMES, setBuddy, setCompanion, useBuddy, useCompanion } from '@/lib/buddy'
import type { Companion } from '@/lib/buddy'
import { setClock, useClock } from '@/lib/clock'
import type { Hours } from '@/lib/clock'
import { costText } from '@/lib/cost-total'
import { buy as buyHat, HATS, hatsCents, setWardrobe, useWardrobe } from '@/lib/hats'
import type { Hat } from '@/lib/hats'
import type { TickerTopic } from '@/lib/headlines'
import { reloadedText } from '@/lib/outcomes'
import { setRave, useRave } from '@/lib/rave'
import { dropDrafts } from '@/lib/reply-draft'
import { setReviewPersonas, usablePersonas, useReviewPersonas } from '@/lib/review-personas'
import { dropReviewRequestDraft } from '@/lib/review-request-draft'
import { setQuips, useQuips } from '@/lib/run-phase'
import { setSeasons, useSeasons } from '@/lib/seasons'
import { setSendKey, useSendKey } from '@/lib/send-key'
import type { SendKey } from '@/lib/send-key'
import { buy as buyShell, SHELLS, setVault, shellsCents, useVault } from '@/lib/shells'
import type { Shell } from '@/lib/shells'
import { clampGap, MAX_GAP, setTickerSettings, useTickerSettings, withTopic } from '@/lib/ticker-settings'
import type { TickerSpeed } from '@/lib/ticker-settings'
import { stamp, useNow } from '@/lib/time'
import { balanceCents } from '@/lib/wallet'
import { paletteOptions, usePalettes } from '@/theme/palette'
import type { Palette } from '@/theme/palette'
import type { ResolvedTheme, ThemePreference } from '@/theme/store'
import { switchPalette, switchTheme } from '@/theme/transition'
import { useTheme } from '@/theme/use-theme'

/**
 * What this browser keeps (the theme, the clock, the send key, chores' findings on the attention list, the review
 * personas, the fun, the session), the limits
 * and trust settings of the workspace's config, and reloading the loop's config.
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

const COMPANIONS: Companion[] = ['sprig', 'ghost']

const HOURS: { value: Hours; label: string }[] = [
    { value: '24', label: '24-hour' },
    { value: '12', label: '12-hour' },
]

const SEND_KEYS: { value: SendKey; label: string }[] = [
    { value: 'enter', label: 'Enter' },
    { value: 'mod-enter', label: 'Ctrl+Enter' },
    { value: 'button', label: 'Button only' },
]

function SettingsPage() {
    return (
        <>
            <PageHeader title="Settings">
                The theme, the clock, the send key, chores&apos; findings on the attention list, your review personas,
                and the fun are kept in this browser. Everything else canopy reads from its config files, whose limits
                and trust settings can be changed here.
            </PageHeader>
            <ThemePanel />
            <ClockPanel />
            <SendKeyPanel />
            <AttentionPanel />
            <ReviewsPanel />
            <NoticePanel />
            <LimitsPanel />
            <ModelsPanel />
            <SkillsPanel />
            <ConfigPanel />
            {/* Second to last: below what changes how canopy works, above signing out. */}
            <FunPanel />
            <SessionPanel />
        </>
    )
}

/** The theme, then the palette each theme wears. Each switches on click, with the theme toggle's reveal. */
function ThemePanel() {
    const { preference } = useTheme()
    const palettes = usePalettes()
    return (
        <Panel>
            <PanelHeader label="Theme" />
            <div className="flex items-center justify-between gap-4 border-b p-3">
                <p className="max-w-3xl text-sm text-muted-foreground">
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
            <PaletteRow theme="light" value={palettes.light} options={paletteOptions('light')}>
                The light theme&apos;s palette: lavender, which tints the canvas with the accent&apos;s hue, a warm
                off-white, a soft sage, or an editor scheme&apos;s light tones, each with an accent of its own.
            </PaletteRow>
            <PaletteRow theme="dark" value={palettes.dark} options={paletteOptions('dark')}>
                The dark theme&apos;s: an indigo slate, a plain grey, a near black, a deep forest green, a plum, or a
                scheme&apos;s dark tones, each with an accent of its own.
            </PaletteRow>
        </Panel>
    )
}

/** One theme's palette, beside the line that says what each is. */
function PaletteRow<T extends ResolvedTheme>({
    theme,
    value,
    options,
    children,
}: {
    theme: T
    value: Palette<T>
    options: { value: Palette<T>; label: string }[]
    children: ReactNode
}) {
    return (
        <div className="flex items-center justify-between gap-4 border-b p-3 last:border-b-0">
            <p className="max-w-3xl text-sm text-muted-foreground">{children}</p>
            <ToggleGroup type="single" value={value} aria-label={theme === 'light' ? 'Light palette' : 'Dark palette'}>
                {options.map((option) => (
                    <ToggleGroupItem
                        key={option.value}
                        value={option.value}
                        data-testid={`palette-${theme}-${option.value}`}
                        onClick={(event) => {
                            void switchPalette(theme, option.value, event.currentTarget)
                        }}
                    >
                        {option.label}
                    </ToggleGroupItem>
                ))}
            </ToggleGroup>
        </div>
    )
}

/**
 * The fun, in one place: an on/off for the ticker, for Sprig (named for whoever sits in its place), for the seasons'
 * decorations, and for the rail's quips, then who sits at the foot of the rail, picked whether it is on or not, since
 * picking one turns it on, then the ticker's pace, the pause between its headlines, and the topics they are drawn
 * from. Its header hides a light switch.
 */
function FunPanel() {
    const { on, speed, gap, hidden } = useTickerSettings()
    const buddy = useBuddy()
    const companion = useCompanion()
    const quips = useQuips()
    const seasons = useSeasons()
    return (
        <Panel>
            <PanelHeader label="Fun">
                <LightSwitch />
            </PanelHeader>
            <div className="flex items-center justify-between gap-4 border-b p-3">
                <p id="fun-items" className="max-w-3xl text-sm text-muted-foreground">
                    The ticker crawls joke headlines across the header. Sprig, at the foot of the side rail, or a Ghost
                    in its place, has a tip for every page; none of them help. Each sits out a window with no room for
                    it. Seasons dress the rail and the logo for the holidays, Sprig or no Sprig. Quips say what each run
                    in the rail is doing, in words of their own.
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
                        {NAMES[companion]}
                    </label>
                    <label htmlFor="fun-seasons" className="inline-flex items-center gap-2 text-xs whitespace-nowrap">
                        <Checkbox
                            id="fun-seasons"
                            checked={seasons === 'on'}
                            data-testid="fun-seasons"
                            onCheckedChange={(checked) => setSeasons(checked === true ? 'on' : 'off')}
                        />
                        Seasons
                    </label>
                    <label htmlFor="fun-quips" className="inline-flex items-center gap-2 text-xs whitespace-nowrap">
                        <Checkbox
                            id="fun-quips"
                            checked={quips === 'on'}
                            data-testid="fun-quips"
                            onCheckedChange={(checked) => setQuips(checked === true ? 'on' : 'off')}
                        />
                        Quips
                    </label>
                </fieldset>
            </div>
            <div className="flex items-center justify-between gap-4 border-b p-3">
                <p className="max-w-3xl text-sm text-muted-foreground">
                    Who sits at the foot of the rail: Sprig, or a Ghost, who floats there instead and has seen some
                    things. Picking one turns it on.
                </p>
                <ToggleGroup
                    type="single"
                    value={companion}
                    aria-label="Companion"
                    onValueChange={(value) => {
                        // A click on the one already picked unpicks it, sending no value: it is still a pick.
                        setCompanion(COMPANIONS.find((c) => c === value) ?? companion)
                        setBuddy('on')
                    }}
                >
                    {COMPANIONS.map((value) => (
                        <ToggleGroupItem key={value} value={value} data-testid={`companion-${value}`}>
                            {NAMES[value]}
                        </ToggleGroupItem>
                    ))}
                </ToggleGroup>
            </div>
            <div className="flex items-center justify-between gap-4 border-b p-3">
                <p className="max-w-3xl text-sm text-muted-foreground">
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
                <label htmlFor="ticker-gap" className="max-w-3xl text-sm text-muted-foreground">
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
                <p id="ticker-topics" className="max-w-3xl text-sm text-muted-foreground">
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
            <ShellShop />
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
 * The wallet the fun shops spend from (src/lib/wallet.ts): everything canopy has spent, as `GET /api/spend` totals
 * it, less every hat and shell bought. Undefined amounts until the total is read.
 */
function useWallet(): { total: number | null | undefined; left: number | undefined } {
    const total = useQuery(spendQuery).data?.total_usd
    const { owned: hats } = useWardrobe()
    const { owned: shells } = useVault()
    return { total, left: total === undefined ? undefined : balanceCents(total, hatsCents(hats) + shellsCents(shells)) }
}

/** What is left in the wallet, in a shop's header, over what canopy has spent; a skeleton till the total is read. */
function WalletReadout({ testId }: { testId: string }) {
    const { total, left } = useWallet()
    return (
        <div className="flex shrink-0 flex-col items-end" data-testid={testId}>
            {left === undefined ? (
                <Skeleton className="h-5 w-14" />
            ) : (
                <Cost usd={left / 100} className="text-sm text-foreground" />
            )}
            <span className="text-2xs text-muted-foreground">
                left of {total === undefined ? '…' : <Cost usd={total} />} spent
            </span>
        </div>
    )
}

/**
 * Sprig's hat shop, in the Fun panel's details, folded under its wallet until opened. Each dollar the agent runtime
 * reports is a dollar for hats, or for the Ghost's shells: they share the wallet. A hat bought goes on at once; one
 * owned goes on or comes off with a click. All sales are final.
 */
function HatShop() {
    const { left } = useWallet()
    const wardrobe = useWardrobe()
    // Folded until asked for: eight hats are a lot of Settings for something most visits leave alone.
    const [open, setOpen] = useState(false)
    return (
        <Collapsible asChild open={open} onOpenChange={setOpen}>
            <div className="border-t" data-testid="hats">
                <div className="flex items-center justify-between gap-4 p-3">
                    <p className="max-w-3xl text-sm text-muted-foreground">
                        Every dollar canopy spends is a dollar for Sprig&apos;s hats. Sprig wears the one you pick while
                        it is on. All sales are final.
                    </p>
                    {/* The wallet at the row's end, so the two shops' wallets line up. */}
                    <div className="flex shrink-0 items-center gap-4">
                        <Disclosure open={open} what="hats" data-testid="hats-toggle" />
                        <WalletReadout testId="hats-wallet" />
                    </div>
                </div>
                <CollapsibleContent asChild>
                    <ul className="grid grid-cols-2 gap-2 border-t p-3 sm:grid-cols-4">
                        {HATS.map((hat) => (
                            <HatItem
                                key={hat.id}
                                hat={hat}
                                owned={wardrobe.owned.includes(hat.id)}
                                worn={wardrobe.worn === hat.id}
                                shortCents={left === undefined ? undefined : Math.max(0, hat.price * 100 - left)}
                                onBuy={() => {
                                    const next = left === undefined ? undefined : buyHat(wardrobe, hat.id, left)
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

/**
 * The Ghost's shell shop, the last of the Fun panel's details, folded under the wallet it shares with Sprig's hats.
 * The Ghost always wears a shell: the Generalist Shell comes free, and a shell bought goes on at once. One owned goes
 * on with a click, and comes off only for another. All sales are final.
 */
function ShellShop() {
    const { left } = useWallet()
    const vault = useVault()
    // Folded until asked for, as the hats are.
    const [open, setOpen] = useState(false)
    return (
        <Collapsible asChild open={open} onOpenChange={setOpen}>
            <div className="border-t" data-testid="shells">
                <div className="flex items-center justify-between gap-4 p-3">
                    <p className="max-w-3xl text-sm text-muted-foreground">
                        The same dollars buy the Ghost new shells, a Sprig Shell among them. The Ghost wears the one you
                        pick while it sits in Sprig&apos;s place. All sales are final.
                    </p>
                    {/* The wallet at the row's end, so the two shops' wallets line up. */}
                    <div className="flex shrink-0 items-center gap-4">
                        <Disclosure open={open} what="shells" data-testid="shells-toggle" />
                        <WalletReadout testId="shells-wallet" />
                    </div>
                </div>
                <CollapsibleContent asChild>
                    <ul className="grid grid-cols-2 gap-2 border-t p-3 sm:grid-cols-5">
                        {SHELLS.map((shell) => (
                            <ShellItem
                                key={shell.id}
                                shell={shell}
                                owned={vault.owned.includes(shell.id)}
                                worn={vault.worn === shell.id}
                                shortCents={left === undefined ? undefined : Math.max(0, shell.price * 100 - left)}
                                onBuy={() => {
                                    const next = left === undefined ? undefined : buyShell(vault, shell.id, left)
                                    if (next) {
                                        setVault(next)
                                    }
                                }}
                                onWear={() => setVault({ ...vault, worn: shell.id })}
                            />
                        ))}
                    </ul>
                </CollapsibleContent>
            </div>
        </Collapsible>
    )
}

/** One shell in the shop: what it looks like and costs, and Buy, or Wear once owned, and Worn while it is. */
function ShellItem({
    shell,
    owned,
    worn,
    shortCents,
    onBuy,
    onWear,
}: {
    shell: Shell
    owned: boolean
    worn: boolean
    shortCents: number | undefined
    onBuy: () => void
    onWear: () => void
}) {
    return (
        <li
            className="flex flex-col items-center gap-1 rounded-md border p-2 text-center"
            data-testid={`shell-${shell.id}`}
        >
            <ShellPreview id={shell.id} className="h-12 w-10" />
            <span className="text-xs text-foreground">{shell.name}</span>
            <span className="grow text-2xs text-muted-foreground">{shell.blurb}</span>
            {owned ? (
                <Button
                    variant={worn ? 'secondary' : 'outline'}
                    size="xs"
                    disabled={worn}
                    onClick={onWear}
                    data-testid={`shell-${shell.id}-wear`}
                >
                    {worn ? 'Worn' : 'Wear'}
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
                    data-testid={`shell-${shell.id}-buy`}
                >
                    Buy <Cost usd={shell.price} />
                </Button>
            )}
        </li>
    )
}

/** How every time of day on the page reads: on a 24-hour or a 12-hour clock, and with its time zone or without. */
function ClockPanel() {
    const clock = useClock()
    const now = new Date(useNow()).toISOString()
    return (
        <Panel>
            <PanelHeader label="Time" />
            <div className="flex items-center justify-between gap-4 border-b p-3">
                <p className="max-w-3xl text-sm text-muted-foreground">
                    How every time on the page reads. Now is{' '}
                    <time dateTime={now} className="readout text-xs text-foreground" data-testid="clock-sample">
                        {stamp(now, clock)}
                    </time>
                    .
                </p>
                <ToggleGroup
                    type="single"
                    value={clock.hours}
                    aria-label="Clock"
                    className="shrink-0"
                    onValueChange={(value) => {
                        const picked = HOURS.find((h) => h.value === value)
                        if (picked) {
                            setClock({ hours: picked.value })
                        }
                    }}
                >
                    {HOURS.map(({ value, label }) => (
                        <ToggleGroupItem key={value} value={value} data-testid={`clock-${value}`}>
                            {label}
                        </ToggleGroupItem>
                    ))}
                </ToggleGroup>
            </div>
            <div className="flex items-center justify-between gap-4 p-3">
                <p id="clock-zone-about" className="max-w-3xl text-sm text-muted-foreground">
                    The time zone after each time, as this browser abbreviates it: EDT, UTC, GMT+2.
                </p>
                <label
                    htmlFor="clock-zone"
                    className="inline-flex shrink-0 items-center gap-2 text-xs whitespace-nowrap"
                >
                    <Checkbox
                        id="clock-zone"
                        checked={clock.zone}
                        aria-describedby="clock-zone-about"
                        data-testid="clock-zone"
                        onCheckedChange={(checked) => setClock({ zone: checked === true })}
                    />
                    Show time zone
                </label>
            </div>
        </Panel>
    )
}

/** Which key sends a reply, a note, a comment, or any other text written to send. */
function SendKeyPanel() {
    const sendKey = useSendKey()
    return (
        <Panel>
            <PanelHeader label="Replies" />
            <div className="flex items-center justify-between gap-4 p-3">
                <p className="max-w-3xl text-sm text-muted-foreground">
                    Which key sends what you write: a reply, a note, a comment, review notes, a lesson, or a notice.
                    Shift+Enter always makes a new line. Ctrl+Enter is ⌘+Enter on a Mac.
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

/**
 * Whether the attention list shows chores' findings: its page, its counter, and the nav's badge. This browser's alone;
 * `canopy status` and the loop never read it, and each chore's page lists its findings either way.
 */
function AttentionPanel() {
    const hidden = useFindingsHidden()
    return (
        <Panel id="attention">
            <PanelHeader label="Attention" />
            <div className="flex items-center justify-between gap-4 p-3">
                <p id="attention-findings-about" className="max-w-3xl text-sm text-muted-foreground">
                    Leave what your chores find off the attention list, its count, and the nav&apos;s badge, so the list
                    holds only what needs you. Each chore&apos;s page still lists its findings, and the attention page
                    says how many it leaves out. Only this browser hides them: <Code>canopy status</Code> lists them
                    all.
                </p>
                <label
                    htmlFor="attention-findings"
                    className="inline-flex shrink-0 items-center gap-2 text-xs whitespace-nowrap"
                >
                    <Checkbox
                        id="attention-findings"
                        checked={hidden}
                        aria-describedby="attention-findings-about"
                        data-testid="attention-findings"
                        onCheckedChange={(checked) => setFindingsHidden(checked === true)}
                    />
                    Hide chore findings
                </label>
            </div>
        </Panel>
    )
}

/** Where the limits and trust settings are changed: a page of their own, as many as they are. */
function LimitsPanel() {
    return (
        <Panel>
            <PanelHeader label="Limits and trust" />
            <div className="flex items-center justify-between gap-4 p-3">
                <p className="text-sm text-muted-foreground">
                    How many workers, chores, and reviews run, how often a ticket is tried, how often the loop ticks,
                    and whose words it acts on. Changed in this workspace&apos;s own config.toml, its comments kept.
                </p>
                <Button asChild variant="outline" data-testid="limits-open">
                    <Link to="/settings/limits">
                        Open
                        <ChevronRight />
                    </Link>
                </Button>
            </div>
        </Panel>
    )
}

/** Where the skills the runtime offers canopy's agents are read: a page of their own, as each read asks the runtime. */
function SkillsPanel() {
    return (
        <Panel>
            <PanelHeader label="Skills" />
            <div className="flex items-center justify-between gap-4 p-3">
                <p className="text-sm text-muted-foreground">
                    Every skill the runtime finds for canopy&apos;s agents: where its file is, and what it says. Read
                    from the runtime when the page opens.
                </p>
                <Button asChild variant="outline" data-testid="skills-open">
                    <Link to="/settings/skills">
                        Open
                        <ChevronRight />
                    </Link>
                </Button>
            </div>
        </Panel>
    )
}

/**
 * The model config chooses for each agent and each chore, read only: the operator chooses one in the file alone, and a
 * ticket's override on its own page.
 */
function ModelsPanel() {
    return (
        <Panel>
            <PanelHeader label="Models" />
            <ConfigModels />
        </Panel>
    )
}

/**
 * The personas the operator prefers for a review they request on the reviews page, which its form starts from: their
 * own, apart from `[personas] reviewer` in the config, which none leaves the request to. A preferred persona since
 * removed, or one canopy would refuse to run, is named, since the form leaves it out.
 */
function ReviewsPanel() {
    const preferred = useReviewPersonas()
    const { data: personas } = useQuery(personasQuery)
    const usable = usablePersonas(preferred, personas)
    const left = preferred.filter((name) => !usable.includes(name))
    const pronoun = left.length === 1 ? 'it' : 'them'
    return (
        <Panel>
            <PanelHeader label="Reviews" />
            <div className="flex items-center justify-between gap-4 p-3">
                <div className="flex flex-col gap-1">
                    <p className="max-w-3xl text-sm text-muted-foreground">
                        The personas a review you request on the Reviews page, or from a PR&apos;s page, is written in,
                        one review in each. Both start from them; you can still pick others for one request. The default
                        leaves it to your config&apos;s <Code>[personas] reviewer</Code>. This choice is yours alone:
                        the loop&apos;s own reviews never read it.
                    </p>
                    {left.length > 0 && (
                        <p className="max-w-3xl text-sm text-status-blocked" data-testid="review-personas-left">
                            Left out of each request, as canopy would refuse {pronoun} now: {left.join(', ')}.
                        </p>
                    )}
                </div>
                <PersonasMenu
                    personas={personas}
                    chosen={preferred}
                    disabled={false}
                    onChange={setReviewPersonas}
                    testId="review-personas"
                />
            </div>
        </Panel>
    )
}

/**
 * Sets the operator's notice to workers, as `canopy notice TEXT --for DURATION` does (docs/design §8): every run
 * dispatched until it lapses hears it. The banner above every page shows it while it is in force, edits, renews, and
 * clears it.
 */
function NoticePanel() {
    return (
        <Panel>
            <PanelHeader label="Notice to workers" />
            <div className="p-3">
                <NoticeForm submit="Set notice" label="Notice to workers" testId="notice">
                    <p className="max-w-3xl text-sm text-muted-foreground">
                        Tell every run dispatched from now on about something passing outside the work, such as a CI
                        outage, as <Code>canopy notice</Code> does. Workers, reviews, and chores hear it, and the
                        overseer holds a failed check it explains. It lapses on its own; setting another replaces it. A
                        run already running keeps the prompt it started with.
                    </p>
                </NoticeForm>
            </div>
        </Panel>
    )
}

/** Asks the loop to read its config files again, as SIGHUP does. A tick running then finishes on the config it had. */
function ConfigPanel() {
    const client = useQueryClient()
    const mutation = useMutation({
        mutationFn: reloadConfig,
        // The models shown above are the loop's: a reload may change them.
        onSuccess: () => client.invalidateQueries({ queryKey: keys.configModels }),
    })
    return (
        <Panel>
            <PanelHeader label="Config" />
            <div className="flex items-center justify-between gap-4 p-3">
                <div className="flex flex-col gap-1">
                    <p className="max-w-3xl text-sm text-muted-foreground">
                        The loop reads the workspace file and your <Code>config.toml</Code> when it starts. Reload reads
                        them again, as <Code>kill -HUP</Code> does; a running tick finishes first. A file that does not
                        load changes nothing.
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
            dropReviewRequestDraft()
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
                    <p className="max-w-3xl text-sm text-muted-foreground">
                        Signed in with the listener secret for 30 days. To sign every browser out, run{' '}
                        <Code>canopy secret --rotate</Code> and restart the loop.
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
