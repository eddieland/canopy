import { PackagePlus } from 'lucide-react'

import type { ChoreDrift } from '@/api/types'
import { InlineCode } from '@/components/rich-text'

/**
 * An example chore installed here that canopy now ships otherwise (docs/design §19): the band heads its page, naming
 * both versions and the command that shows how they differ, until the operator puts the two back together. Nothing
 * waits on it, since the copy keeps running as installed, so it wears no status tint.
 */
export function ChoreDriftBanner({ name, drift }: { name: string; drift: ChoreDrift | null }) {
    if (drift === null) {
        return null
    }
    const lead = drift.standing === 'changed' ? 'Canopy ships a newer version' : 'Differs from the version canopy ships'
    return (
        <section
            aria-label={lead}
            data-testid="chore-drift"
            className="flex items-start gap-3 rounded-md border bg-surface-raised px-3 py-2"
        >
            <PackagePlus aria-hidden className="mt-0.5 size-4 shrink-0 text-muted-foreground" />
            <div className="flex min-w-0 flex-col gap-0.5">
                <p className="text-sm wrap-break-word">
                    <span className="font-medium">{lead}: </span>
                    {standingText(drift)}
                </p>
                <p className="text-xs text-muted-foreground">
                    <InlineCode text={diffText(name, drift)} />
                </p>
            </div>
        </section>
    )
}

// What moved apart, naming the versions on each side.
function standingText(drift: ChoreDrift): string {
    if (drift.standing === 'changed') {
        const by = drift.installed_by === null ? 'the canopy' : `canopy ${drift.installed_by}`
        return `canopy ${drift.shipped_by} ships its prompt or agent otherwise than ${by} that installed it.`
    }
    return (
        `it was installed before canopy kept what it installed it from, and its copy differs from what canopy ` +
        `${drift.shipped_by} ships.`
    )
}

// The command that shows how, and what each side of its diff is.
function diffText(name: string, drift: ChoreDrift): string {
    return drift.standing === 'changed'
        ? `\`canopy chore diff ${name}\` shows what canopy changed since, and what you changed in the copy.`
        : `\`canopy chore diff ${name}\` shows your copy against what canopy ships, but not whose edits are whose.`
}
