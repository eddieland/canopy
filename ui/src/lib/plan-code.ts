// A plan's code block of any language but Mermaid's (src/lib/plan-diagram.ts draws those): a `pre` around a `code`, as
// `CodeBlock` renders one, with room beside it for its actions, its copy button, which the page draws there
// (src/lib/block-slots.ts, src/components/block-actions.tsx).
import type { Node as ProseMirrorNode } from '@tiptap/pm/model'
import type { NodeView, ViewMutationRecord } from '@tiptap/pm/view'

import { newSlotId } from '@/lib/block-slots'
import type { BlockSlots } from '@/lib/block-slots'

/** A code block that is not a diagram, as `CodeBlock` renders one, and the room for its actions beside it. */
export class CodeView implements NodeView {
    readonly dom: HTMLElement
    readonly contentDOM: HTMLElement
    private readonly actions: HTMLElement
    private readonly slots: BlockSlots
    private readonly id = newSlotId()
    private readonly language: unknown
    private text: string

    constructor(node: ProseMirrorNode, slots: BlockSlots) {
        this.slots = slots
        this.text = node.textContent
        this.language = node.attrs['language']
        this.dom = document.createElement('div')
        // A block whose actions show while it is hovered (`block-actions`, src/index.css).
        this.dom.className = 'plan-code group/block'
        this.contentDOM = child(child(this.dom, 'pre'), 'code')
        if (typeof this.language === 'string' && this.language) {
            this.contentDOM.className = `language-${this.language}`
        }
        this.actions = child(this.dom, 'div')
        this.actions.className = 'block-actions'
        this.actions.contentEditable = 'false'
        this.publish()
    }

    // Drawn again if it changes language, which may make it a diagram.
    update(node: ProseMirrorNode): boolean {
        if (node.type.name !== 'codeBlock' || node.attrs['language'] !== this.language) {
            return false
        }
        if (node.textContent !== this.text) {
            this.text = node.textContent
            this.publish()
        }
        return true
    }

    // Its actions are not the document: what is done to them, and what changes in them, is their own.
    stopEvent(event: Event): boolean {
        return event.target instanceof globalThis.Node && this.actions.contains(event.target)
    }

    ignoreMutation(mutation: ViewMutationRecord): boolean {
        return mutation.type !== 'selection' && this.actions.contains(mutation.target)
    }

    destroy(): void {
        this.slots.remove(this.id)
    }

    // Says what the block's actions act on now: its code.
    private publish(): void {
        this.slots.put({ id: this.id, kind: 'code', slot: this.actions, text: this.text })
    }
}

// A new `tag` element, the last of `parent`'s children.
function child<K extends keyof HTMLElementTagNameMap>(parent: HTMLElement, tag: K): HTMLElementTagNameMap[K] {
    const element = document.createElement(tag)
    parent.append(element)
    return element
}
