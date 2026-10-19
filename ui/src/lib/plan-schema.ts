// What a plan's document is made of in the editor (src/components/plan-editor.tsx), and how it reads and writes
// Markdown, which the journal keeps. Tiptap's StarterKit, task lists, and tables cover what a planner writes; the rest
// keeps what the editor has no node for as the characters it was, so opening a plan and saving it never drops a
// part of it. A plan is model-written (TRUST_MODEL T1), so its HTML is never read as HTML: a tag is a verbatim atom
// that shows and writes back its characters, as an image is, which would otherwise fetch from another origin
// (ui/AGENTS.md). A link keeps its Markdown and shows its address on hover, but is not a link: the web UI links a URL
// only to itself (D113). A line the source wraps inside a paragraph is a soft break of its own, drawn as a space and
// written back as the wrap it was. Text pasted as Markdown is read as Markdown, through the same parser, and what is
// copied out of more than one block is written as Markdown.
import { Extension, getTextBetween, getTextSerializersFromSchema, mergeAttributes, Node } from '@tiptap/core'
import type { AnyExtension, JSONContent, MarkdownToken } from '@tiptap/core'
import { Heading } from '@tiptap/extension-heading'
import { Link } from '@tiptap/extension-link'
import { TaskItem, TaskList } from '@tiptap/extension-list'
import { TableKit } from '@tiptap/extension-table'
import { Markdown } from '@tiptap/markdown'
import type { Node as ProseMirrorNode } from '@tiptap/pm/model'
import { Plugin, PluginKey } from '@tiptap/pm/state'
import { StarterKit } from '@tiptap/starter-kit'

import { ATOM } from '@/lib/plan-anchors'

// A mark as a document's JSON holds it.
type JSONMark = NonNullable<JSONContent['marks']>[number]

// A line that starts a heading, a list item (a task's too), a quote, a fence, or a table row.
const MARKDOWN_BLOCK = /^ {0,3}(?:#{1,6} \S|[-*+] \S|\d{1,9}[.)] \S|> ?\S|```|~~~|\|.*\|\s*$)/mu
// Bold, inline code, or a link.
const MARKDOWN_INLINE = /\*\*[^*\n]+\*\*|`[^`\n]+`|\[[^\]\n]+\]\([^)\s]+\)/u

/** The extensions of a plan's document, with `more` (the comments' highlights) after them. */
export function planExtensions(more: AnyExtension[] = []): AnyExtension[] {
    return [
        StarterKit.configure({
            // Markdown has no underline, a link is ours, and so is a heading (below).
            underline: false,
            link: false,
            heading: false,
        }),
        PlanHeading.configure({ levels: [...PLAN_LEVELS] }),
        PlanLink.configure({ openOnClick: false, autolink: false, linkOnPaste: false }),
        TaskList,
        PlanTaskItem.configure({ nested: true }),
        TableKit.configure({ table: { resizable: false } }),
        VerbatimBlock,
        VerbatimInline,
        ImageAsText,
        SoftBreak,
        PasteMarkdown,
        CopyMarkdown,
        PlanMarkdown.configure({ indentation: { style: 'space', size: 2 } }),
        ...more,
    ]
}

/**
 * Whether pasted text reads as Markdown: a line that starts a heading, a list item, a quote, a fence, or a table row,
 * or inline marks (`**bold**`, `` `code` ``, `[a link](url)`). Prose without them pastes as the text it is.
 */
export function readsAsMarkdown(text: string): boolean {
    return MARKDOWN_BLOCK.test(text) || MARKDOWN_INLINE.test(text)
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
        } else if (node.type.name === 'softBreak') {
            text += ' '
            positions.push(pos)
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

// The heading levels a plan has, `#` to `####`.
const PLAN_LEVELS = [1, 2, 3, 4] as const
// A plan sits in its page's Plan panel, whose title is an h2 under the page's h1, so its `#` is drawn as an h3 and
// each level under it a step lower, to `####` as an h6: the page's outline skips no level. The level the Markdown
// says rides on `data-level`, so what the editor copies reads back at the level it was.
const PLAN_DEPTH = 2

const PlanHeading = Heading.extend({
    parseHTML() {
        return [1, 2, 3, 4, 5, 6].map((tag) => ({
            tag: `h${tag}`,
            getAttrs: (element: HTMLElement) => {
                const level = Number(element.dataset['level'] ?? tag)
                return PLAN_LEVELS.some((l) => l === level) ? { level } : false
            },
        }))
    },
    renderHTML({ node, HTMLAttributes }) {
        const level = Number(node.attrs['level'])
        return [`h${level + PLAN_DEPTH}`, mergeAttributes(HTMLAttributes, { 'data-level': level }), 0]
    },
})

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

// A line the source wraps inside a paragraph, as planners and this repository wrap Markdown. To a reader it is a space,
// so the paragraph reflows to the editor's width; it writes back as the wrap it was, the space before it and the
// indent after it included. Left as a newline in a text node, the browser would draw it as a line break, since the
// editor keeps whitespace as typed, and the first keystroke near it would read it back from the page as a hard break:
// a change to the plan, and an edit that starts at the break, which cuts short a comment on the words after it. Two or
// more spaces, or a backslash, before the newline make a hard break instead, which marked reads as `br`.
const SoftBreak = Node.create({
    name: 'softBreak',
    group: 'inline',
    inline: true,
    selectable: false,
    addAttributes() {
        return { raw: { default: '\n' } }
    },
    parseHTML() {
        return [{ tag: 'span[data-soft-break]' }]
    },
    renderHTML() {
        return ['span', { 'data-soft-break': '' }, ' ']
    },
    renderText: () => ' ',
    markdownTokenizer: {
        name: 'softBreak',
        level: 'inline',
        // Where the text before it stops: at the spaces before a newline, so that two of them still reach `br`.
        start: (src) => src.search(/ *\n/u),
        tokenize: (src) => {
            const match = /^ ?\n[ \t]*/u.exec(src)
            // A newline that ends the text is no break between words.
            const between = match !== null && /\S/u.test(src.slice(match[0].length))
            return between ? { type: 'softBreak', raw: match[0], text: match[0] } : undefined
        },
    },
    parseMarkdown: (token, helpers) => helpers.createNode('softBreak', { raw: token.raw ?? '\n' }),
    renderMarkdown: (node: JSONContent) => String(node.attrs?.['raw'] ?? '\n'),
})

// Markdown, with each soft break written as the text it was before the marks around it are: a node of its own would
// close a mark it sits inside and open it again after it, so `**two\nwords**` would write back as two bold spans.
const PlanMarkdown = Markdown.extend({
    onBeforeCreate(event) {
        this.parent?.(event)
        const editor = this.editor
        editor.getMarkdown = () => editor.markdown?.serialize(softBreaksAsText(editor.getJSON())) ?? ''
    },
})

// `node` with each soft break turned into its text, joined to the text beside it. Its marks are those of the text on
// both sides of it, which the parser gives the text alone. A soft break at either end of its block, which an edit can
// leave there, separates nothing and is dropped.
//
// `indent` is what the line after each soft break in `node` starts with beyond the wrap itself: in a list item's first
// paragraph, its marker's width, since the list writes that paragraph after its marker and indents no line of it.
function softBreaksAsText(node: JSONContent, indent = ''): JSONContent {
    if (node.content === undefined) {
        return node
    }
    const content: JSONContent[] = []
    node.content.forEach((child, i, all) => {
        if (child.type !== 'softBreak') {
            content.push(softBreaksAsText(child, indentIn(node, child, i, indent)))
            return
        }
        if (i === 0 || i === all.length - 1) {
            return
        }
        const after = all[i + 1]?.marks ?? []
        const marks = (all[i - 1]?.marks ?? []).filter((mark) => after.some((other) => sameMark(mark, other)))
        const wrap = String(child.attrs?.['raw'] ?? '\n')
        // In a list item, the marker's width in place of what the reader left of the source's indent, which differs
        // between Tiptap's lists.
        const raw = indent ? wrap.replace(/\n[ \t]*/u, `\n${indent}`) : wrap
        content.push({ type: 'text', text: raw, marks })
    })
    return { ...node, content: joinText(content) }
}

// The indent of the lines a soft break starts in `child`, the `i`th child of `node`: a list hands each item its
// marker's width (`- `, `- [ ] ` as `- `, `12. `), which the item hands its first paragraph. Any other line is
// indented, or quoted, by the block around it as it is written.
function indentIn(node: JSONContent, child: JSONContent, i: number, indent: string): string {
    if (node.type === 'bulletList' || node.type === 'taskList') {
        return '  '
    }
    if (node.type === 'orderedList') {
        const start = Number(node.attrs?.['start'] ?? 1)
        return ' '.repeat(`${(Number.isFinite(start) ? start : 1) + i}. `.length)
    }
    if (node.type === 'listItem' || node.type === 'taskItem') {
        return i === 0 && child.type === 'paragraph' ? indent : ''
    }
    return ''
}

// Adjacent text nodes with the same marks, as one.
function joinText(content: JSONContent[]): JSONContent[] {
    const joined: JSONContent[] = []
    for (const node of content) {
        const last = joined.at(-1)
        if (last?.type === 'text' && node.type === 'text' && sameMarks(last, node)) {
            joined[joined.length - 1] = { ...last, text: `${last.text ?? ''}${node.text ?? ''}` }
        } else {
            joined.push(node)
        }
    }
    return joined
}

function sameMarks(a: JSONContent, b: JSONContent): boolean {
    const theirs = b.marks ?? []
    const ours = a.marks ?? []
    return ours.length === theirs.length && ours.every((mark, i) => sameMark(mark, theirs[i]))
}

function sameMark(a: JSONMark, b: JSONMark | undefined): boolean {
    return JSON.stringify(a) === JSON.stringify(b)
}

// Text pasted as Markdown, as a planner's plan or a chat's answer is copied from a terminal or an editor, becomes the
// headings, lists, and marks it writes, read by the plan's own parser, so its HTML stays characters as a plan's does.
// What pastes as it always has: a copy from the editor itself, which carries its own slice (`data-pm-slice`); text that
// does not read as Markdown; a paste with Shift held, the browser's paste as plain text; and a paste into a code block,
// where a YAML list or a shell comment is code, not Markdown, and ProseMirror keeps it as its characters.
const PasteMarkdown = Extension.create({
    name: 'pasteMarkdown',
    addProseMirrorPlugins() {
        const editor = this.editor
        let shift = false
        return [
            new Plugin({
                key: new PluginKey('pasteMarkdown'),
                props: {
                    handleDOMEvents: {
                        keydown: (_, event) => {
                            shift = event.shiftKey
                            return false
                        },
                        keyup: (_, event) => {
                            shift = event.shiftKey
                            return false
                        },
                    },
                    handlePaste: (view, event) => {
                        const text = event.clipboardData?.getData('text/plain') ?? ''
                        const html = event.clipboardData?.getData('text/html') ?? ''
                        const inCode = view.state.selection.$from.parent.type.spec.code === true
                        if (shift || inCode || html.includes('data-pm-slice') || !readsAsMarkdown(text)) {
                            return false
                        }
                        return editor.commands.insertContent(text, { contentType: 'markdown' })
                    },
                },
            }),
        ]
    },
})

// A task item whose text wraps, as `- [ ] a task\n  that wraps`. Tiptap's task list reads the first line as the task's
// text and the lines under it as blocks of their own, so a wrapped task would become two paragraphs. A paragraph that
// comes straight after the first line, with no blank line between, is the same paragraph, as CommonMark reads it: its
// words join the task's text after a soft break. A blank line before it shows as a leading `space` token, and keeps it
// apart. In a list that mixes tasks and bullets, Tiptap trims the blank line away before it lexes the lines under a
// task (with marked's whole lexer, whose tokens carry `links`), so nothing there can be told apart and nothing joins.
const PlanTaskItem = TaskItem.extend({
    parseMarkdown(token, helpers) {
        const found: unknown = token['nestedTokens']
        const nested = Array.isArray(found) ? (found as MarkdownToken[]) : undefined
        const first = nested?.[0]
        if (nested === undefined || first?.type !== 'paragraph' || 'links' in nested) {
            return this.parent?.(token, helpers) ?? []
        }
        const wrap: MarkdownToken = { type: 'softBreak', raw: '\n', text: '\n' }
        const tokens = [...(token.tokens ?? []), wrap, ...(first.tokens ?? [])]
        return this.parent?.({ ...token, tokens, nestedTokens: nested.slice(1) }, helpers) ?? []
    },
})

// What is copied out of the plan, as plain text: the Markdown that writes it when it spans blocks (lines of a list,
// a heading and its paragraph, rows of a table), so a list item keeps its `- ` and a heading its `#`. A selection
// inside one block copies as its words, as it would from any page: as Markdown, `snake_case` would come out escaped
// and a code span in backticks. The HTML copied beside it is ProseMirror's own, which a paste back into a plan reads.
const CopyMarkdown = Extension.create({
    name: 'copyMarkdown',
    // Ahead of Tiptap's own serializer, which copies every selection as its words.
    priority: 1000,
    addProseMirrorPlugins() {
        const editor = this.editor
        return [
            new Plugin({
                key: new PluginKey('copyMarkdown'),
                props: {
                    // The slice is the selection's, with the blocks around it (`Selection.content`).
                    clipboardTextSerializer: (slice, view) => {
                        const { $from, $to } = view.state.selection
                        // The words as Tiptap's serializer gives them, a soft break a space (its `renderText`).
                        const words = getTextBetween(
                            view.state.doc,
                            { from: $from.pos, to: $to.pos },
                            { textSerializers: getTextSerializersFromSchema(view.state.schema) },
                        )
                        if ($from.sameParent($to) && $from.parent.isTextblock) {
                            return words
                        }
                        const doc: JSONContent = { type: 'doc', content: slice.content.toJSON() as JSONContent[] }
                        return editor.markdown?.serialize(softBreaksAsText(doc)) ?? words
                    },
                },
            }),
        ]
    },
})

// An image, as the characters that wrote it: the editor never fetches it.
const ImageAsText = Extension.create({
    name: 'imageAsText',
    markdownTokenName: 'image',
    parseMarkdown: (token, helpers) => helpers.createNode('verbatimInline', { raw: token.raw ?? '' }),
})
