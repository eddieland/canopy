import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { createFileRoute } from '@tanstack/react-router'
import { LogOut, Monitor, Moon, Sun, type LucideIcon } from 'lucide-react'

import { signOut } from '@/api/mutations'
import { keys, sessionQuery } from '@/api/queries'
import { Input } from '@/components/input'
import { Notice } from '@/components/notice'
import { Button } from '@/components/ui/button'

import { PageHeader, Panel, PanelHeader } from '@/components/panel'
import { type SendKey, setSendKey, useSendKey } from '@/lib/send-key'
import { clampGap, MAX_GAP, setTickerSettings, type TickerSpeed, useTickerSettings } from '@/lib/ticker-settings'
import { cn } from '@/lib/utils'
import type { ThemePreference } from '@/theme/store'
import { switchTheme } from '@/theme/transition'
import { useTheme } from '@/theme/use-theme'

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

const SEND_KEYS: { value: SendKey; label: string }[] = [
    { value: 'enter', label: 'Enter' },
    { value: 'mod-enter', label: 'Ctrl+Enter' },
    { value: 'button', label: 'Button only' },
]

// A segmented control: a row of buttons, the pressed one raised.
const SEGMENTS = 'inline-flex rounded-md border bg-background p-0.5'
const SEGMENT = [
    'inline-flex h-7 items-center gap-1.5 rounded-sm px-2.5 text-xs',
    'text-muted-foreground transition-colors hover:text-foreground',
    'aria-pressed:bg-surface-raised aria-pressed:text-foreground',
    'aria-pressed:shadow-xs',
]

function SettingsPage() {
    const { preference } = useTheme()
    return (
        <>
            <PageHeader label="Preferences" title="Settings">
                Kept in this browser. Everything else canopy reads from its config file.
            </PageHeader>
            <Panel>
                <PanelHeader label="Theme" />
                <div className="flex items-center justify-between gap-4 p-3">
                    <p className="text-sm text-muted-foreground">
                        Follows the system unless you pick one. Syncs across tabs.
                    </p>
                    <fieldset className={SEGMENTS}>
                        <legend className="sr-only">Theme</legend>
                        {THEMES.map(({ value, label, icon: Icon }) => (
                            <button
                                key={value}
                                type="button"
                                aria-pressed={preference === value}
                                data-testid={`theme-${value}`}
                                onClick={(event) => switchTheme(value, event.currentTarget)}
                                className={cn(SEGMENT)}
                            >
                                <Icon className="size-3.5" />
                                {label}
                            </button>
                        ))}
                    </fieldset>
                </div>
            </Panel>
            <TickerPanel />
            <SendKeyPanel />
            <SessionPanel />
        </>
    )
}

/** The header ticker's pace and the pause between its headlines. */
function TickerPanel() {
    const { speed, gap } = useTickerSettings()
    return (
        <Panel>
            <PanelHeader label="Ticker" />
            <div className="flex items-center justify-between gap-4 border-b p-3">
                <p className="text-sm text-muted-foreground">
                    How fast the headlines in the header crawl, one at a time. Off hides them.
                </p>
                <fieldset className={SEGMENTS}>
                    <legend className="sr-only">Ticker speed</legend>
                    {SPEEDS.map(({ value, label }) => (
                        <button
                            key={value}
                            type="button"
                            aria-pressed={speed === value}
                            data-testid={`ticker-${value}`}
                            onClick={() => setTickerSettings({ speed: value })}
                            className={cn(SEGMENT)}
                        >
                            {label}
                        </button>
                    ))}
                </fieldset>
            </div>
            <div className="flex items-center justify-between gap-4 p-3">
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
                            if (seconds !== undefined) setTickerSettings({ gap: seconds })
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
                <fieldset className={cn(SEGMENTS, 'shrink-0')}>
                    <legend className="sr-only">Send a reply with</legend>
                    {SEND_KEYS.map(({ value, label }) => (
                        <button
                            key={value}
                            type="button"
                            aria-pressed={sendKey === value}
                            data-testid={`send-key-${value}`}
                            onClick={() => setSendKey(value)}
                            className={cn(SEGMENT)}
                        >
                            {label}
                        </button>
                    ))}
                </fieldset>
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
    if (data?.token === 'open') return null
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
