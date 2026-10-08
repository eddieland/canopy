import { createFileRoute } from '@tanstack/react-router'
import { Monitor, Moon, Sun, type LucideIcon } from 'lucide-react'

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
        </>
    )
}
