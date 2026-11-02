import { Link } from '@tanstack/react-router'
import { Moon, Sun } from 'lucide-react'
import { useRef, useState } from 'react'

import { Button } from '@/components/ui/button'
import { HoverCard, HoverCardContent, HoverCardTrigger } from '@/components/ui/hover-card'
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group'
import { paletteOptions, usePalettes } from '@/theme/palette'
import type { ResolvedTheme } from '@/theme/store'
import { switchPalette, switchTheme } from '@/theme/transition'
import { useTheme } from '@/theme/use-theme'

/**
 * Flips between light and dark with a circular reveal from the button. System is chosen in Settings.
 * The new icon spins in. Hovered, a card offers the shown theme's palettes, each switched with the same reveal.
 */
export function ThemeToggle() {
    const { resolved } = useTheme()
    const next = resolved === 'dark' ? 'light' : 'dark'
    const [open, setOpen] = useState(false)
    // While a pick's reveal runs, the page under it takes no pointer, so the card hears the pointer leave though it
    // has not, and the browser's idea of what is hovered is stale for a moment after. So the card stays open until
    // every reveal is over (a count: a pick during a reveal cuts that one short, settling it early), and then the
    // pointer's next move, whose target is hit-tested afresh, closes it unless it lands on the card or the button.
    const revealing = useRef(0)
    const card = useRef<HTMLDivElement>(null)
    const button = useRef<HTMLButtonElement>(null)
    const pick = (reveal: Promise<void>): void => {
        revealing.current += 1
        void reveal.finally(() => {
            revealing.current -= 1
            if (revealing.current === 0) {
                document.addEventListener('pointermove', closeIfLeft, { once: true, capture: true })
            }
        })
    }
    const closeIfLeft = (event: PointerEvent): void => {
        const target = event.target instanceof Node ? event.target : null
        if (revealing.current === 0 && ![card.current, button.current].some((element) => element?.contains(target))) {
            setOpen(false)
        }
    }
    return (
        <HoverCard
            open={open}
            onOpenChange={(opening) => {
                if (opening || revealing.current === 0) {
                    setOpen(opening)
                }
            }}
        >
            <HoverCardTrigger asChild>
                <Button
                    ref={button}
                    variant="ghost"
                    size="icon-sm"
                    aria-label={`Switch to ${next} theme`}
                    data-testid="theme-toggle"
                    onClick={(event) => switchTheme(next, event.currentTarget)}
                >
                    {resolved === 'dark' ? (
                        <Sun key="sun" className="animate-spin-in" />
                    ) : (
                        <Moon key="moon" className="animate-spin-in" />
                    )}
                </Button>
            </HoverCardTrigger>
            <HoverCardContent ref={card} className="w-48" data-testid="palette-card">
                <PalettePicker theme={resolved} onPick={pick} />
            </HoverCardContent>
        </HoverCard>
    )
}

/**
 * The palettes `theme` can wear, the one it wears picked, and a pointer to Settings for the other theme's. A pick
 * switches with a reveal from the item pressed, handed to `onPick` until it is over.
 */
function PalettePicker({ theme, onPick }: { theme: ResolvedTheme; onPick: (reveal: Promise<void>) => void }) {
    const palettes = usePalettes()
    const label = theme === 'light' ? 'Light palette' : 'Dark palette'
    return (
        <div className="flex flex-col gap-2.5 text-xs">
            <span className="font-medium">{label}</span>
            {/* Switched on click, not on a value change, so the reveal grows from the item pressed. */}
            <ToggleGroup
                type="single"
                orientation="vertical"
                value={palettes[theme]}
                aria-label={label}
                className="w-full flex-col items-stretch"
            >
                {paletteOptions(theme).map((option) => (
                    <ToggleGroupItem
                        key={option.value}
                        value={option.value}
                        className="justify-start"
                        data-testid={`quick-palette-${option.value}`}
                        onClick={(event) => onPick(switchPalette(theme, option.value, event.currentTarget))}
                    >
                        {option.label}
                    </ToggleGroupItem>
                ))}
            </ToggleGroup>
            <Link to="/settings" className="text-muted-foreground hover:text-foreground">
                Both themes&apos; palettes are in Settings.
            </Link>
        </div>
    )
}
