import { SeasonDecoration } from '@/components/season'
import { useFits } from '@/hooks/use-fits'
import { useSeason } from '@/lib/seasons'
import { cn } from '@/lib/utils'

/**
 * The rail's gap with Sprig off: in a season, the season's scene (src/components/season.tsx) stands at its foot, on
 * the spend's hairline, where Sprig would, with what flies or hangs over it. As tall as Sprig, it steps out of a slot
 * too short to hold it whole, rather than squeeze or cover the blocks above. Out of season, or with the seasons off in
 * Settings, the gap is only room.
 */
export function SeasonSlot() {
    const season = useSeason()
    const [slot, fits] = useFits(holds)
    return (
        <div ref={slot} className="flex min-h-0 flex-1 flex-col justify-end print:hidden">
            {season === null ? null : (
                <div data-testid="rail-season" className={cn('flex h-26 shrink-0 px-2 pb-1', !fits && 'invisible')}>
                    <SeasonDecoration id={season} aloft />
                </div>
            )}
        </div>
    )
}

/** Whether the slot holds the scene, its one child, whole. */
function holds(slot: HTMLElement): boolean {
    const scene = slot.firstElementChild
    return scene instanceof HTMLElement && scene.offsetHeight <= slot.clientHeight
}
