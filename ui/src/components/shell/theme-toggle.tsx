import { Moon, Sun } from 'lucide-react'

import { Button } from '@/components/ui/button'
import { switchTheme } from '@/theme/transition'
import { useTheme } from '@/theme/use-theme'

/** Flips between light and dark with a circular reveal from the button. System is chosen in Settings.
 * The new icon spins in. */
export function ThemeToggle() {
    const { resolved } = useTheme()
    const next = resolved === 'dark' ? 'light' : 'dark'
    return (
        <Button
            variant="ghost"
            size="icon-sm"
            aria-label={`Switch to ${next} theme`}
            title={`Switch to ${next} theme`}
            data-testid="theme-toggle"
            onClick={(event) => switchTheme(next, event.currentTarget)}
        >
            {resolved === 'dark' ? (
                <Sun key="sun" className="animate-spin-in" />
            ) : (
                <Moon key="moon" className="animate-spin-in" />
            )}
        </Button>
    )
}
