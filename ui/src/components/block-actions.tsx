import { useSyncExternalStore } from 'react'
import type { ReactNode } from 'react'
import { createPortal } from 'react-dom'

import { CopyButton } from '@/components/copy-button'
import { blockSlots } from '@/lib/block-slots'

/**
 * A block's actions, at its top right corner over it (`block-actions`, src/index.css): what takes the block elsewhere,
 * a diagram's source or a code block's text. They show while the block, an ancestor marked `group/block`, is hovered,
 * or one of them holds the focus, and always on a touch screen. The block is positioned, so they sit in its corner.
 */
export function BlockActions({ children }: { children: ReactNode }) {
    return <div className="block-actions">{children}</div>
}

/** A diagram's actions: its Mermaid source copied, exactly as the fence holds it, without the fence's lines. */
export function DiagramActions({ source }: { source: string }) {
    return <CopyButton text={source} label="Mermaid source" />
}

/**
 * The actions of the blocks of a plan's document, the editor `owner`'s, each drawn into its block's room for them
 * (`src/lib/block-slots.ts`): through a portal, so they render in the page's tree, with its toasts, though ProseMirror
 * draws the block around them.
 */
export function PlanBlockActions({ owner }: { owner: object }) {
    const slots = blockSlots(owner)
    const blocks = useSyncExternalStore(slots.subscribe, slots.snapshot)
    return blocks.map((block) => createPortal(<DiagramActions source={block.source} />, block.slot, String(block.id)))
}
