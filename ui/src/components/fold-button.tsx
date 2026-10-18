import { ChevronsUpDown } from 'lucide-react'

import { Button } from '@/components/ui/button'

/**
 * A fold's button, which draws the next step of what the page held back (`foldWords`): a diff's lines, a transcript's
 * rows. A fold only adds, so it is a plain button, not a `Disclosure`.
 */
export function FoldButton({ label, onShow, className }: { label: string; onShow: () => void; className?: string }) {
    return (
        <Button variant="ghost" size="xs" onClick={onShow} className={className}>
            <ChevronsUpDown />
            {label}
        </Button>
    )
}
