import { Command, CornerDownLeft } from 'lucide-react'

import { Kbd } from '@/components/ui/kbd'

/**
 * The keys of a send button's shortcut (`Control+Enter`, from `useSendKeys`) as one keycap after its label, tinted with
 * the button's own color: ⌘ and Enter as glyphs, Ctrl as its word. Nothing under Button only.
 */
export function SendKeycap({ keys }: { keys: string | undefined }) {
    if (keys === undefined) {
        return null
    }
    return (
        <Kbd aria-hidden className="ml-0.5 bg-current/15 text-current">
            {keys.split('+').map((key) => {
                if (key === 'Meta') {
                    return <Command key={key} />
                }
                if (key === 'Enter') {
                    return <CornerDownLeft key={key} />
                }
                return <span key={key}>Ctrl</span>
            })}
        </Kbd>
    )
}
