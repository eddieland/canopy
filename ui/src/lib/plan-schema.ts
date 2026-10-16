// What a plan's document is made of in the editor (src/components/plan-editor.tsx), and how it reads and writes
// Markdown, which the journal keeps. Tiptap's StarterKit, task lists, and tables cover what a planner writes; the rest
// keeps what the editor has no node for as the characters it was, so opening a plan and saving it never drops a
// part of it. A plan is model-written (TRUST_MODEL T1), so its HTML is never read as HTML: a tag is a verbatim atom
// that shows and writes back its characters, as an image is, which would otherwise fetch from another origin
// (ui/AGENTS.md). A link keeps its Markdown and shows its address on hover, but is not a link: the web UI links a URL
// only to itself (D113).
import { Extension, Node } from '@tiptap/core'
import type { AnyExtension, JSONContent } from '@tiptap/core'
import { Link } from '@tiptap/extension-link'
import { TaskItem, TaskList } from '@tiptap/extension-list'
import { TableKit } from '@tiptap/extension-table'
import { Markdown } from '@tiptap/markdown'
import type { Node as ProseMirrorNode } from '@tiptap/pm/model'
import { StarterKit } from '@tiptap/starter-kit'

import { ATOM } from '@/lib/plan-anchors'

/** The extensions of a plan's document, with `more` (the comments' highlights) after them. */
export function planExtensions(more: AnyExtension[] = []): AnyExtension[] {
    return [
        StarterKit.configure({
            // Markdown has no underline, and a link is ours (below).
            underline: false,
            link: false,
            heading: { levels: [1, 2, 3, 4] },
        }),
        PlanLink.configure({ openOnClick: false, autolink: false, linkOnPaste: false }),
        TaskList,
        TaskItem.configure({ nested: true }),
        TableKit.configure({ table: { resizable: false } }),
        VerbatimBlock,
        VerbatimInline,
        ImageAsText,
        Markdown.configure({ indentation: { style: 'space', size: 2 } }),
        ...more,
    ]
}

/**
 * A plan's text as the editor holds it, for anchoring comments (`src/lib/plan-anchors.ts`): each block's text on a
 * line of its own, a hard break a newline, an inline atom one `ATOM`. `positions[i]` is the document position of
 * `text[i]`, or -1 for a newline between blocks, which no position holds.
 */
export function docText(doc: ProseMirrorNode): { text: string; positions: number[] } {
    let text = ''
    const positions: number[] = []
    doc.descendants((node, pos) => {
        if (node.isBlock && text.length > 0 && !text.endsWith('\n')) {
            text += '\n'
            positions.push(-1)
        }
        if (node.isText) {
            const value = node.text ?? ''
            text += value
            for (let i = 0; i < value.length; i += 1) {
                positions.push(pos + i)
            }
        } else if (node.type.name === 'hardBreak') {
            text += '\n'
            positions.push(pos)
        } else if (node.isInline && node.isAtom) {
            text += ATOM
            positions.push(pos)
        }
        return true
    })
    return { text, positions }
}

/** The document range that `text[start]` to `text[end - 1]` of `docText` cover, or undefined when they hold none. */
export function rangeOf(positions: number[], start: number, end: number): { from: number; to: number } | undefined {
    let first = start
    while (first < end && (positions[first] ?? -1) < 0) {
        first += 1
    }
    let last = end - 1
    while (last >= first && (positions[last] ?? -1) < 0) {
        last -= 1
    }
    if (first > last) {
        return undefined
    }
    return { from: positions[first] ?? 0, to: (positions[last] ?? 0) + 1 }
}

/** The span of `docText`'s text that the document range `from` to `to` covers. */
export function spanOf(positions: number[], from: number, to: number): { start: number; end: number } {
    let start = 0
    while (start < positions.length && (positions[start] ?? -1) < from) {
        start += 1
    }
    let end = positions.length
    while (end > start && ((positions[end - 1] ?? -1) >= to || (positions[end - 1] ?? -1) < 0)) {
        end -= 1
    }
    return { start, end }
}

// A link, kept with its address so it writes back as it was read, shown as underlined text with the address on
// hover. The editor never navigates, and nothing here is an anchor element.
const PlanLink = Link.extend({
    renderHTML({ HTMLAttributes }) {
        const href = typeof HTMLAttributes['href'] === 'string' ? HTMLAttributes['href'] : ''
        return ['span', { class: 'plan-link', title: href }, 0]
    },
})

// What marked reads as HTML, block or inline, kept as its characters. Inline HTML never reaches a handler in
// @tiptap/markdown (it is parsed as HTML in place), so the inline atom brings its own tokenizer, which marked tries
// before its own; a block reaches the `html` handler.
const TAG = /^(?:<!--[\s\S]*?-->|<\/?[A-Za-z][\w-]*(?:\s[^<>]*)?\/?>)/u

const VerbatimInline = Node.create({
    name: 'verbatimInline',
    group: 'inline',
    inline: true,
    atom: true,
    selectable: true,
    addAttributes() {
        return { raw: { default: '' } }
    },
    parseHTML() {
        return [{ tag: 'span[data-verbatim]', getAttrs: (element) => ({ raw: element.textContent }) }]
    },
    renderHTML({ node }) {
        return ['span', { 'data-verbatim': '', class: 'plan-verbatim' }, String(node.attrs['raw'] ?? '')]
    },
    markdownTokenizer: {
        name: 'verbatimInline',
        level: 'inline',
        start: (src) => src.indexOf('<'),
        tokenize: (src) => {
            const match = TAG.exec(src)
            return match ? { type: 'verbatimInline', raw: match[0], text: match[0] } : undefined
        },
    },
    parseMarkdown: (token, helpers) => helpers.createNode('verbatimInline', { raw: token.raw ?? '' }),
    renderMarkdown: (node: JSONContent) => String(node.attrs?.['raw'] ?? ''),
})

const VerbatimBlock = Node.create({
    name: 'verbatimBlock',
    group: 'block',
    atom: true,
    selectable: true,
    addAttributes() {
        return { raw: { default: '' } }
    },
    parseHTML() {
        return [{ tag: 'pre[data-verbatim]', getAttrs: (element) => ({ raw: element.textContent }) }]
    },
    renderHTML({ node }) {
        return ['pre', { 'data-verbatim': '', class: 'plan-verbatim-block' }, String(node.attrs['raw'] ?? '')]
    },
    markdownTokenName: 'html',
    parseMarkdown: (token, helpers) => {
        const raw = (token.raw ?? token.text ?? '').trimEnd()
        if (!raw) {
            return []
        }
        return helpers.createNode(token.block === true ? 'verbatimBlock' : 'verbatimInline', { raw })
    },
    renderMarkdown: (node: JSONContent) => String(node.attrs?.['raw'] ?? ''),
})

// An image, as the characters that wrote it: the editor never fetches it.
const ImageAsText = Extension.create({
    name: 'imageAsText',
    markdownTokenName: 'image',
    parseMarkdown: (token, helpers) => helpers.createNode('verbatimInline', { raw: token.raw ?? '' }),
})
