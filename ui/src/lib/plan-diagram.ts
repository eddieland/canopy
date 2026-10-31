// A plan's Mermaid fence, drawn as its diagram (src/lib/diagram.ts) beside the code block that writes it. The code is
// the document: comments anchor to its words, the word diff marks them, and the Markdown writes it back as it was. The
// diagram is the code's picture, drawn as an image, which shows nothing the code does not say. Once it is drawn, the
// code hides behind a Source toggle, and shows again while the caret is in it (being edited, under the picture it
// draws), while a comment's highlight or a change is marked in it, and when the diagram cannot be drawn, under why.
// An arrow key at the edge of the block beside a diagram puts the caret in its code, so the keyboard always reaches it.
//
// A code block of any other language draws as it always has, a `pre` around a `code`, as `CodeBlock` renders it.
import { Extension } from '@tiptap/core'
import type { Node as ProseMirrorNode } from '@tiptap/pm/model'
import { Plugin, PluginKey, TextSelection } from '@tiptap/pm/state'
import type { EditorState } from '@tiptap/pm/state'
import { Decoration, DecorationSet } from '@tiptap/pm/view'
import type { EditorView, NodeView, ViewMutationRecord } from '@tiptap/pm/view'

import type { Drawn, NotDrawn } from '@/lib/diagram'

// Kept in step with DIAGRAM_LANGUAGE in src/lib/diagram.ts, which loads only when a diagram is drawn.
const LANGUAGE = 'mermaid'
// How long the code rests after a keystroke before its diagram is drawn again, in milliseconds.
const REST_MS = 400
// The class the code block holding the caret wears, which shows its code.
const EDITING = 'plan-diagram-editing'
// The arrow keys, and the way each goes.
const ARROWS: Partial<Record<string, 'left' | 'right' | 'up' | 'down'>> = {
    ArrowLeft: 'left',
    ArrowRight: 'right',
    ArrowUp: 'up',
    ArrowDown: 'down',
}

/** Draws a plan's Mermaid code blocks as their diagrams. */
export const PlanDiagrams = Extension.create({
    name: 'planDiagrams',
    addProseMirrorPlugins() {
        const editor = this.editor
        return [
            new Plugin({
                key: new PluginKey('planDiagrams'),
                props: {
                    nodeViews: { codeBlock: (node) => (isDiagram(node) ? new DiagramView(node) : codeView(node)) },
                    decorations: (state) => (editor.isEditable ? editing(state) : DecorationSet.empty),
                    handleKeyDown: (view, event) => editor.isEditable && enterDiagram(view, event),
                },
            }),
        ]
    },
})

/** Whether `node` is a code block that writes a diagram. */
export function isDiagram(node: ProseMirrorNode): boolean {
    return node.type.name === 'codeBlock' && node.attrs['language'] === LANGUAGE
}

// The diagram's code block that holds the caret, marked so, or none.
function editing(state: EditorState): DecorationSet {
    const { $from } = state.selection
    if (!state.selection.empty || !isDiagram($from.parent)) {
        return DecorationSet.empty
    }
    const start = $from.before()
    return DecorationSet.create(state.doc, [Decoration.node(start, start + $from.parent.nodeSize, { class: EDITING })])
}

// An arrow key at the edge of a block, going toward a diagram beside it, puts the caret in the diagram's code: at its
// end going back, at its start going on. Left to the browser, the caret would have to cross the picture, which is no
// part of the document, into code clipped out of sight, and it stops on either side of the picture as it pleases.
function enterDiagram(view: EditorView, event: KeyboardEvent): boolean {
    const way = ARROWS[event.key]
    const { selection, doc } = view.state
    const modified = event.shiftKey || event.altKey || event.ctrlKey || event.metaKey
    if (way === undefined || modified || !selection.empty || selection.$from.depth === 0) {
        return false
    }
    if (!view.endOfTextblock(way)) {
        return false
    }
    const back = way === 'left' || way === 'up'
    const $edge = doc.resolve(back ? selection.$from.before() : selection.$from.after())
    const beside = back ? $edge.nodeBefore : $edge.nodeAfter
    if (beside === null || !isDiagram(beside)) {
        return false
    }
    const caret = back ? $edge.pos - 1 : $edge.pos + 1
    view.dispatch(view.state.tr.setSelection(TextSelection.create(doc, caret)).scrollIntoView())
    return true
}

// A code block that is not a diagram, as `CodeBlock` renders one.
function codeView(node: ProseMirrorNode): NodeView {
    const dom = document.createElement('pre')
    const contentDOM = child(dom, 'code')
    const language: unknown = node.attrs['language']
    if (typeof language === 'string' && language) {
        contentDOM.className = `language-${language}`
    }
    return {
        dom,
        contentDOM,
        // Drawn again if it changes language, which may make it a diagram.
        update: (next) => next.type === node.type && next.attrs['language'] === language,
    }
}

// A diagram's code block: its code, and the picture it draws.
class DiagramView implements NodeView {
    readonly dom: HTMLElement
    readonly contentDOM: HTMLElement
    private readonly figure: HTMLElement
    private readonly image: HTMLImageElement
    private readonly reason: HTMLElement
    private readonly toggle: HTMLButtonElement
    private text: string
    // Which draw the picture shows: one that ends after a later one began is dropped.
    private draws = 0
    private timer: ReturnType<typeof setTimeout> | undefined
    private readonly unsubscribe: () => void

    constructor(node: ProseMirrorNode) {
        this.text = node.textContent
        this.dom = document.createElement('div')
        this.dom.className = 'plan-diagram'
        this.dom.dataset['diagram'] = 'pending'
        const pre = child(this.dom, 'pre')
        this.contentDOM = child(pre, 'code')
        this.contentDOM.className = `language-${LANGUAGE}`

        this.figure = child(this.dom, 'figure')
        this.figure.className = 'plan-diagram-figure'
        this.figure.contentEditable = 'false'
        this.image = child(this.figure, 'img')
        this.image.alt = 'A diagram'
        this.image.hidden = true
        this.reason = child(this.figure, 'figcaption')
        this.toggle = child(this.figure, 'button')
        this.toggle.type = 'button'
        this.toggle.className = 'plan-diagram-toggle'
        this.toggle.textContent = 'Source'
        this.toggle.setAttribute('aria-pressed', 'false')
        this.toggle.addEventListener('click', () => {
            const shown = this.toggle.getAttribute('aria-pressed') !== 'true'
            this.toggle.setAttribute('aria-pressed', String(shown))
            this.dom.toggleAttribute('data-source', shown)
        })

        this.unsubscribe = onThemeChange(() => {
            this.draw()
        })
        this.draw()
    }

    update(node: ProseMirrorNode): boolean {
        if (!isDiagram(node)) {
            return false
        }
        if (node.textContent !== this.text) {
            this.text = node.textContent
            // A draw of the code before this edit, still under way, is dropped when it ends.
            this.draws += 1
            clearTimeout(this.timer)
            this.timer = setTimeout(() => {
                this.draw()
            }, REST_MS)
        }
        return true
    }

    // The picture is not the document: what changes in it, and what is done to it, is its own.
    stopEvent(event: Event): boolean {
        return event.target instanceof globalThis.Node && this.figure.contains(event.target)
    }

    ignoreMutation(mutation: ViewMutationRecord): boolean {
        if (mutation.type === 'selection') {
            return false
        }
        return mutation.target === this.dom || this.figure.contains(mutation.target)
    }

    destroy(): void {
        clearTimeout(this.timer)
        this.draws += 1
        this.unsubscribe()
    }

    private draw(): void {
        void this.drawNow()
    }

    private async drawNow(): Promise<void> {
        this.draws += 1
        const draw = this.draws
        const source = this.text
        let result: Drawn | NotDrawn
        try {
            const { drawDiagram } = await import('@/lib/diagram')
            result = await drawDiagram(source)
        } catch (error) {
            result = { error: `it could not be drawn: ${String(error)}` }
        }
        if (draw !== this.draws) {
            return
        }
        if ('error' in result) {
            this.dom.dataset['diagram'] = 'failed'
            this.image.hidden = true
            this.image.removeAttribute('src')
            this.reason.textContent = `Not drawn: ${result.error}.`
            return
        }
        this.dom.dataset['diagram'] = 'drawn'
        this.image.alt = `A ${KIND_NAMES[result.kind] ?? 'diagram'}, drawn from the Mermaid source beside it`
        this.image.src = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(result.svg)}`
        this.image.hidden = false
        this.reason.textContent = ''
    }
}

// A new `tag` element, the last of `parent`'s children.
function child<K extends keyof HTMLElementTagNameMap>(parent: HTMLElement, tag: K): HTMLElementTagNameMap[K] {
    const element = document.createElement(tag)
    parent.append(element)
    return element
}

// What each kind of diagram is called, for the picture's alternative text.
const KIND_NAMES: Partial<Record<string, string>> = {
    'flowchart-v2': 'flowchart',
    flowchart: 'flowchart',
    sequence: 'sequence diagram',
    stateDiagram: 'state diagram',
}

// The theme and palette are classes and data on <html> (src/theme/), which a diagram's colors come from.
const listeners = new Set<() => void>()
let watcher: MutationObserver | undefined

function onThemeChange(listener: () => void): () => void {
    listeners.add(listener)
    if (watcher === undefined) {
        // Written again with the value it had, an attribute changes nothing a diagram shows.
        watcher = new MutationObserver((mutations) => {
            const root = document.documentElement
            if (mutations.every((m) => m.attributeName === null || m.oldValue === root.getAttribute(m.attributeName))) {
                return
            }
            for (const each of listeners) {
                each()
            }
        })
        watcher.observe(document.documentElement, {
            attributes: true,
            attributeOldValue: true,
            attributeFilter: ['class', 'data-light-palette', 'data-dark-palette'],
        })
    }
    return () => {
        listeners.delete(listener)
        if (listeners.size === 0) {
            watcher?.disconnect()
            watcher = undefined
        }
    }
}
