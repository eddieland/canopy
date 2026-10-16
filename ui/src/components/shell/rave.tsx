import { useRave } from '@/lib/rave'

/**
 * The lightswitch rave (ui/DESIGN.md, Fun): once the light switch in the Settings Fun panel's header is flipped, The
 * Cheat flicks the lights off and on over the whole app while party beams sweep through the dark, until the switch is
 * flipped back. Only for the eye: it takes no pointer, so everything under it still works, a screen reader never meets
 * it, and it is not printed. Under reduced motion the lights stay off and the beams hold still.
 */
export function Rave() {
    const rave = useRave()
    if (rave !== 'on') {
        return null
    }
    return (
        <div
            aria-hidden
            data-testid="rave"
            className="pointer-events-none fixed inset-0 z-50 overflow-hidden print:hidden"
        >
            <div className="rave-dark absolute inset-0" />
            {/* Wider than the window's diagonal every way, so its corners never show as it turns. */}
            <div className="rave-beams absolute -inset-[50vmax]" />
        </div>
    )
}
