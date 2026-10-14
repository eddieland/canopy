import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { createFileRoute } from '@tanstack/react-router'
import { LogOut, Monitor, Moon, RefreshCw, Sun } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'

import { reloadConfig, signOut } from '@/api/mutations'
import { keys, sessionQuery } from '@/api/queries'
import { Input } from '@/components/input'
import { Notice } from '@/components/notice'
import { PageHeader, Panel, PanelHeader } from '@/components/panel'
import { Button } from '@/components/ui/button'
import { Checkbox } from '@/components/ui/checkbox'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import { setBuddy, useBuddy } from '@/lib/buddy'
import type { BuddySetting } from '@/lib/buddy'
import type { TickerTopic } from '@/lib/headlines'
import { reloadedText } from '@/lib/outcomes'
import { setSendKey, useSendKey } from '@/lib/send-key'
import type { SendKey } from '@/lib/send-key'
import { clampGap, MAX_GAP, setTickerSettings, useTickerSettings, withTopic } from '@/lib/ticker-settings'
import type { TickerSpeed } from '@/lib/ticker-settings'
import type { ThemePreference } from '@/theme/store'
import { switchTheme } from '@/theme/transition'
import { useTheme } from '@/theme/use-theme'

/** What this browser keeps (the theme, the ticker, the send key, the session), and reloading the loop's config. */
export const Route = createFileRoute('/settings')({
    component: SettingsPage,
})

const THEMES: { value: ThemePreference; label: string; icon: LucideIcon }[] = [
    { value: 'light', label: 'Light', icon: Sun },
    { value: 'dark', label: 'Dark', icon: Moon },
    { value: 'system', label: 'System', icon: Monitor },
]

const SPEEDS: { value: TickerSpeed; label: string }[] = [
    { value: 'off', label: 'Off' },
    { value: 'slow', label: 'Slow' },
    { value: 'normal', label: 'Normal' },
    { value: 'spicy', label: 'Spicy' },
]

const TOPICS: { value: TickerTopic; label: string }[] = [
    { value: 'programming', label: 'Programming' },
    { value: 'vibes', label: 'Vibe coding' },
    { value: 'tips', label: 'Tips' },
]

const BUDDY: { value: BuddySetting; label: string }[] = [
    { value: 'on', label: 'On' },
    { value: 'off', label: 'Off' },
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
                The theme, the ticker, Sprig, and the send key are kept in this browser. Everything else canopy reads
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
            <TickerPanel />
            <BuddyPanel />
            <SendKeyPanel />
            <ConfigPanel />
            <SessionPanel />
        </>
    )
}

/** The header ticker's pace, the pause between its headlines, and the topics they are drawn from. */
function TickerPanel() {
    const { speed, gap, hidden } = useTickerSettings()
    return (
        <Panel>
            <PanelHeader label="Ticker" />
            <div className="flex items-center justify-between gap-4 border-b p-3">
                <p className="text-sm text-muted-foreground">
                    How fast the headlines in the header crawl, one at a time. Off hides them.
                </p>
                <ToggleGroup
                    type="single"
                    value={speed}
                    aria-label="Ticker speed"
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
                        disabled={speed === 'off'}
                        className="readout h-8 w-20 text-right"
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
                    Which headlines it shows. Tips about canopy are mixed in with the jokes.
                </p>
                <fieldset aria-labelledby="ticker-topics" className="flex shrink-0 items-center gap-4">
                    {TOPICS.map(({ value, label }) => (
                        <label key={value} className="inline-flex items-center gap-2 text-xs whitespace-nowrap">
                            <Checkbox
                                checked={!hidden.includes(value)}
                                disabled={speed === 'off'}
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
        </Panel>
    )
}

/** Whether Sprig sits in the corner offering tips. */
function BuddyPanel() {
    const buddy = useBuddy()
    return (
        <Panel>
            <PanelHeader label="Sprig" />
            <div className="flex items-center justify-between gap-4 p-3">
                <p className="text-sm text-muted-foreground">
                    The helper in the bottom-left corner, with a tip for every page. None of them help. Off hides it.
                </p>
                <ToggleGroup
                    type="single"
                    value={buddy}
                    aria-label="Sprig"
                    className="shrink-0"
                    onValueChange={(value) => {
                        const picked = BUDDY.find((b) => b.value === value)
                        if (picked) {
                            setBuddy(picked.value)
                        }
                    }}
                >
                    {BUDDY.map(({ value, label }) => (
                        <ToggleGroupItem key={value} value={value} data-testid={`buddy-${value}`}>
                            {label}
                        </ToggleGroupItem>
                    ))}
                </ToggleGroup>
            </div>
        </Panel>
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
        mutationFn: signOut,
        onSuccess: (session) => {
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
