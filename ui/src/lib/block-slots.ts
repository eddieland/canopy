// Where a plan's document keeps room for a block's actions (src/components/block-actions.tsx): an element of a block's
// node view, outside the document, which ProseMirror draws and the page fills through a portal, so the actions are
// React in the page's own tree, with its toasts, though the document around them is not. A diagram's, for now
// (src/lib/plan-diagram.ts).

/** A diagram's room for its actions, and what they act on. */
export interface DiagramSlot {
    /** Which block it is, for a key that holds while the block does. */
    id: number
    /** What kind of block it is. */
    kind: 'diagram'
    /** The element its actions go in. */
    slot: HTMLElement
    /** The diagram's Mermaid source, as the plan's file has it between its fence lines. */
    source: string
}

/** A block's room for its actions. */
export type BlockSlot = DiagramSlot

/** The blocks of one document that keep room for their actions, as they are now, and who hears when they change. */
export class BlockSlots {
    private blocks: readonly BlockSlot[] = []
    private readonly listeners = new Set<() => void>()

    /** Calls `listener` whenever a block is added, changed, or removed; returns what stops it. */
    readonly subscribe = (listener: () => void): (() => void) => {
        this.listeners.add(listener)
        return () => {
            this.listeners.delete(listener)
        }
    }

    /** The blocks as they are now: the same list until one changes. */
    readonly snapshot = (): readonly BlockSlot[] => this.blocks

    /** Adds `block`, or puts it in place of the block of its id. */
    put(block: BlockSlot): void {
        const at = this.blocks.findIndex((each) => each.id === block.id)
        this.blocks = at === -1 ? [...this.blocks, block] : this.blocks.with(at, block)
        this.notify()
    }

    /** Removes the block of `id`. */
    remove(id: number): void {
        this.blocks = this.blocks.filter((each) => each.id !== id)
        this.notify()
    }

    private notify(): void {
        for (const listener of this.listeners) {
            listener()
        }
    }
}

const documents = new WeakMap<object, BlockSlots>()
let ids = 0

/** The blocks with room for their actions in the document of `owner`, its editor. */
export function blockSlots(owner: object): BlockSlots {
    let slots = documents.get(owner)
    if (slots === undefined) {
        slots = new BlockSlots()
        documents.set(owner, slots)
    }
    return slots
}

/** A new block's id, never given before. */
export function newSlotId(): number {
    ids += 1
    return ids
}
