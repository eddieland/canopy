import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { createFileRoute } from '@tanstack/react-router'
import { LogOut, Monitor, Moon, Sun, type LucideIcon } from 'lucide-react'

import { signOut } from '@/api/mutations'
import { keys, sessionQuery } from '@/api/queries'
import { Notice } from '@/components/notice'
import { Button } from '@/components/ui/button'

import { PageHeader, Panel, PanelHeader } from '@/components/panel'
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
                    <fieldset className="inline-flex rounded-md border bg-background p-0.5">
                        <legend className="sr-only">Theme</legend>
                        {THEMES.map(({ value, label, icon: Icon }) => (
                            <button
                                key={value}
                                type="button"
                                aria-pressed={preference === value}
                                data-testid={`theme-${value}`}
                                onClick={(event) => switchTheme(value, event.currentTarget)}
                                className={cn(
                                    'inline-flex h-7 items-center gap-1.5 rounded-sm px-2.5 text-xs',
                                    'text-muted-foreground transition-colors hover:text-foreground',
                                    'aria-pressed:bg-surface-raised aria-pressed:text-foreground',
                                    'aria-pressed:shadow-xs',
                                )}
                            >
                                <Icon className="size-3.5" />
                                {label}
                            </button>
                        ))}
                    </fieldset>
                </div>
            </Panel>
            <SessionPanel />
        </>
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
