import { within } from '@testing-library/dom'
import { Editor } from '@tiptap/core'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { drawDiagram } from '@/lib/diagram'
import type { Drawn, NotDrawn } from '@/lib/diagram'
import { planExtensions } from '@/lib/plan-schema'

// Mermaid draws in a real browser alone (e2e/plan-diagrams.spec.ts): here a diagram is drawn as its source says.
vi.mock(import('@/lib/diagram'), () => ({
    DIAGRAM_LANGUAGE: 'mermaid' as const,
    drawDiagram: vi.fn<(source: string) => Promise<Drawn | NotDrawn>>((source) =>
        Promise.resolve(
            source.startsWith('pie')
                ? { error: 'a pie diagram is not drawn here' }
                : { svg: `<svg>${source}</svg>`, kind: 'sequence' },
        ),
    ),
}))

const DIAGRAM = '```mermaid\nsequenceDiagram\n    A->>B: hi\n```'
const PLAN = `# Plan\n\nIn order:\n\n${DIAGRAM}\n\nThen:\n\n\`\`\`python\nprint("hi")\n\`\`\`\n`

const editors: Editor[] = []

// The end of the document's code block, where text typed there goes.
function codeEnd(editor: Editor): number {
    let end = 0
    editor.state.doc.descendants((node, pos) => {
        if (node.type.name === 'codeBlock') {
            end = pos + node.nodeSize - 1
        }
    })
    return end
}

function open(markdown: string): { editor: Editor; root: HTMLElement } {
    const root = document.createElement('div')
    document.body.append(root)
    const editor = new Editor({
        element: root,
        extensions: planExtensions(),
        content: markdown,
        contentType: 'markdown',
    })
    editors.push(editor)
    return { editor, root }
}

afterEach(() => {
    for (const editor of editors.splice(0)) {
        editor.destroy()
    }
    document.body.replaceChildren()
    document.documentElement.classList.remove('dark')
    vi.mocked(drawDiagram).mockClear()
})

describe('a Mermaid code block', () => {
    it('is drawn as its diagram, an image of the SVG, with its source under Source', async () => {
        const { root } = open(PLAN)
        const image = await within(root).findByRole('img', { name: /^A sequence diagram/u })
        expect(image.getAttribute('src')).toBe(
            `data:image/svg+xml;charset=utf-8,${encodeURIComponent('<svg>sequenceDiagram\n    A->>B: hi</svg>')}`,
        )
        const source = within(root).getByRole('button', { name: 'Source' })
        expect(source.getAttribute('aria-pressed')).toBe('false')
        source.click()
        expect(source.getAttribute('aria-pressed')).toBe('true')
        expect(drawDiagram).toHaveBeenCalledTimes(1)
    })

    it('writes back as the Markdown it was, and another language stays a code block', async () => {
        const { editor, root } = open(PLAN)
        await within(root).findByRole('img')
        expect(within(root).getAllByRole('img')).toHaveLength(1)
        expect(within(root).getByText('print("hi")').closest('pre')).not.toBeNull()
        expect(editor.getMarkdown()).toContain(DIAGRAM)
        expect(editor.getMarkdown()).toContain('```python\nprint("hi")\n```')
    })

    it('says why it was not drawn, with no image', async () => {
        const { root } = open('```mermaid\npie\n    "a": 1\n```')
        expect(await within(root).findByText('Not drawn: a pie diagram is not drawn here.')).toBeTruthy()
        expect(within(root).queryByRole('img')).toBeNull()
    })

    it('is drawn again once its source rests after an edit, and when the theme changes', async () => {
        const { editor, root } = open(DIAGRAM)
        await within(root).findByRole('img')
        vi.useFakeTimers()
        try {
            const end = codeEnd(editor)
            editor.commands.insertContentAt(end, '\n    B->>A: bye')
            editor.commands.insertContentAt(end + 1, ' ')
            expect(drawDiagram).toHaveBeenCalledTimes(1)
            await vi.runAllTimersAsync()
            expect(drawDiagram).toHaveBeenCalledTimes(2)
            expect(vi.mocked(drawDiagram).mock.lastCall?.[0]).toContain('B->>A: bye')
        } finally {
            vi.useRealTimers()
        }
        document.documentElement.classList.add('dark')
        await vi.waitFor(() => {
            expect(drawDiagram).toHaveBeenCalledTimes(3)
        })
    })

    it('drops a draw of the code before an edit that ends after it', async () => {
        let finish: ((drawn: Drawn) => void) | undefined
        vi.mocked(drawDiagram).mockImplementationOnce(
            () =>
                new Promise((resolve) => {
                    finish = resolve
                }),
        )
        const { editor, root } = open(DIAGRAM)
        await vi.waitFor(() => {
            expect(drawDiagram).toHaveBeenCalledTimes(1)
        })
        editor.commands.insertContentAt(codeEnd(editor), '\n    B->>A: bye')
        finish?.({ svg: '<svg>before the edit</svg>', kind: 'sequence' })
        const image = await within(root).findByRole('img')
        expect(decodeURIComponent(image.getAttribute('src') ?? '')).toContain('B->>A: bye')
    })
})
