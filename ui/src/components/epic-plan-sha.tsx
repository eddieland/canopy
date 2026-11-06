import { Copyable } from '@/components/copy-button'
import { Tip } from '@/components/tip'

// How much of a plan's hash a page shows: enough to tell two apart at a glance, the whole on hover and copied whole.
const HASH_SHOWN = 12

/**
 * An epic plan's SHA-256 as a readout: its first characters, the whole on hover, and copied whole by the button beside
 * it unless `copy` is false, for a hash in a sentence. Apart from the epic's plan page, so a page that names a plan by
 * its hash, as a member's plan page does, loads no plan editor.
 */
export function EpicPlanSha({ sha256, copy = true }: { sha256: string; copy?: boolean }) {
    const shown = (
        <Tip fact={sha256} mono>
            <span className="readout">{sha256.slice(0, HASH_SHOWN)}</span>
        </Tip>
    )
    return copy ? (
        <Copyable text={sha256} label="plan hash">
            {shown}
        </Copyable>
    ) : (
        shown
    )
}
