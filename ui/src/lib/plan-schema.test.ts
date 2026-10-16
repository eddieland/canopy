import { Editor } from '@tiptap/core'
import { afterEach, describe, expect, it } from 'vitest'

import { ATOM } from '@/lib/plan-anchors'
import { docText, planExtensions, rangeOf, readsAsMarkdown, spanOf } from '@/lib/plan-schema'

const editors: Editor[] = []

function open(markdown: string): Editor {
    const editor = new Editor({ extensions: planExtensions(), content: markdown, contentType: 'markdown' })
    editors.push(editor)
    return editor
}

// How many paragraphs the plan's document holds.
function paragraphs(markdown: string): number {
    let count = 0
    open(markdown).state.doc.descendants((node) => {
        count += node.type.name === 'paragraph' ? 1 : 0
    })
    return count
}

afterEach(() => {
    for (const editor of editors.splice(0)) {
        editor.destroy()
    }
})

describe('planExtensions', () => {
    it('writes back what a planner writes as it was read', () => {
        const plan = [
            '# Plan',
            '',
            'Some **bold**, *italic*, ~~struck~~, and `code`.',
            '',
            '## Steps',
            '',
            '1. Read the ticket',
            '2. Change `export.py`',
            '   - stream rows',
            '',
            '- [ ] write the test',
            '- [x] read the code',
            '',
            '> A risk.',
            '',
            '```python',
            'def export(): ...',
            '```',
            '',
            '---',
        ].join('\n')
        expect(open(plan).getMarkdown()).toBe(plan)
    })

    it('reflows a wrapped line as a space and writes it back as it was wrapped', () => {
        const plan = [
            'In **web**, a new route,',
            'which streams the rows. A *phrase that',
            'wraps* and [a link that',
            'wraps](https://x.test/a) stay whole. ',
            'A space before the wrap stays too.',
            '',
            '> A risk',
            '> that wraps.',
        ].join('\n')
        const editor = open(plan)
        const texts: string[] = []
        editor.state.doc.descendants((node) => {
            if (node.isText) {
                texts.push(node.text ?? '')
            }
        })
        expect(texts.join('')).not.toContain('\n')
        expect(editor.getText()).toContain('a new route, which streams')
        expect(editor.getMarkdown()).toBe(plan)
    })

    it.each([
        ['a bullet', '- an item\n  that wraps\n- two'],
        ['a numbered item', '1. an item\n   that wraps\n2. two'],
        ['a numbered item past nine', '9. nine\n10. ten\n    that wraps'],
        ['a nested item', '- outer\n  - inner\n    that wraps'],
        ['a task', '- [ ] a task\n  that wraps\n- [x] done'],
        ['a task with a second paragraph', '- [ ] a task\n\n  its own paragraph'],
    ])('writes back %s that wraps as it was read', (_, plan) => {
        expect(open(plan).getMarkdown()).toBe(plan)
    })

    it('reads a wrapped task as one paragraph, and one after a blank line as two', () => {
        expect(paragraphs('- [ ] a task\n  that wraps')).toBe(1)
        expect(paragraphs('- [ ] a task\n\n  its own paragraph')).toBe(2)
        // After a bullet, Tiptap reads the task's lines with the blank line trimmed away: nothing there joins.
        expect(paragraphs('- a bullet\n- [ ] a task\n\n  its own paragraph')).toBe(3)
    })

    it('keeps a hard break apart from a soft one', () => {
        const editor = open('One  \ntwo\nthree')
        const types: string[] = []
        editor.state.doc.firstChild?.forEach((node) => {
            types.push(node.type.name)
        })
        expect(types).toEqual(['text', 'hardBreak', 'text', 'softBreak', 'text'])
        expect(editor.getMarkdown()).toBe('One  \ntwo\nthree')
    })

    it('drops a soft break an edit leaves at the end of its paragraph', () => {
        const editor = open('One\ntwo')
        editor.commands.deleteRange({ from: 5, to: 8 })
        expect(editor.getMarkdown()).toBe('One')
    })

    it('keeps a table', () => {
        const markdown = open('| File | Why |\n| --- | --- |\n| a.py | rows |').getMarkdown()
        expect(markdown).toContain('| a.py | rows |')
    })

    it('keeps HTML and images as their characters, never as markup', () => {
        const editor = open(
            'Use <b>raw</b> and ![chart](https://x.test/c.png).\n\n<details>\n<summary>more</summary>\n</details>',
        )
        const html = editor.getHTML()
        expect(html).not.toContain('<b>')
        expect(html).not.toContain('<img')
        expect(html).not.toContain('<details>')
        expect(editor.getMarkdown()).toBe(
            'Use <b>raw</b> and ![chart](https://x.test/c.png).\n\n<details>\n<summary>more</summary>\n</details>',
        )
    })

    it('keeps a link and its address but draws no anchor element', () => {
        const editor = open('See [the docs](https://x.test/docs).')
        expect(editor.getHTML()).not.toContain('<a')
        expect(editor.getHTML()).toContain('title="https://x.test/docs"')
        expect(editor.getMarkdown()).toBe('See [the docs](https://x.test/docs).')
    })
})

describe('docText', () => {
    it('puts each block on its own line and maps every character to its position', () => {
        const editor = open('# Plan\n\nOne <b>two</b>.\n\n- three')
        const { text, positions } = docText(editor.state.doc)
        expect(text).toBe(`Plan\nOne ${ATOM}two${ATOM}.\nthree`)
        expect(positions).toHaveLength(text.length)
        const start = text.indexOf('two')
        const range = rangeOf(positions, start, start + 3)
        if (!range) {
            throw new Error('no range')
        }
        expect(editor.state.doc.textBetween(range.from, range.to)).toBe('two')
        expect(spanOf(positions, range.from, range.to)).toEqual({ start, end: start + 3 })
    })

    it('reads a soft break as a space, at its own position', () => {
        const editor = open('One\ntwo')
        const { text, positions } = docText(editor.state.doc)
        expect(text).toBe('One two')
        expect(editor.state.doc.nodeAt(positions[3] ?? 0)?.type.name).toBe('softBreak')
    })

    it('has no range for a span of block breaks alone', () => {
        const { text, positions } = docText(open('a\n\nb').state.doc)
        expect(rangeOf(positions, text.indexOf('\n'), text.indexOf('\n') + 1)).toBeUndefined()
    })
})

describe('readsAsMarkdown', () => {
    it.each([
        '## Rollout',
        'Intro\n- ship it',
        '1. first',
        '- [ ] a task',
        '> a risk',
        '```\ncode\n```',
        '| a | b |',
        'a **bold** word',
        'run `make check`',
        'see [the docs](https://x.test)',
    ])('reads %j as Markdown', (text) => {
        expect(readsAsMarkdown(text)).toBe(true)
    })

    it.each(['Just a sentence.', 'https://x.test/a', '2 * 3 = 6', '#hashtag', '-5 degrees'])(
        'reads %j as text',
        (text) => {
            expect(readsAsMarkdown(text)).toBe(false)
        },
    )
})
