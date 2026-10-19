import { describe, expect, it } from 'vitest'

import { foldDetails, hidesText } from './details'

describe('foldDetails', () => {
    it('folds a block under its summary, dropping the blank lines that only lay it out', () => {
        const text = [
            'Missing guard on null.',
            '',
            '<details>',
            '<summary><b>Prompt for AI agents</b></summary>',
            '',
            '```',
            'Check `user` before use.',
            '```',
            '',
            '</details>',
            '',
            'Thanks.',
        ].join('\r\n')
        expect(foldDetails(text)).toEqual([
            { kind: 'text', text: 'Missing guard on null.' },
            {
                kind: 'details',
                summary: 'Prompt for AI agents',
                open: false,
                parts: [{ kind: 'text', text: '```\nCheck `user` before use.\n```' }],
            },
            { kind: 'text', text: 'Thanks.' },
        ])
    })

    it('nests blocks, keeps one written open, and names one with no summary as GitHub does', () => {
        const text = '<details open><summary>Outer</summary>\nbefore\n<details>\ninner\n</details>\nafter\n</details>'
        expect(foldDetails(text)).toEqual([
            {
                kind: 'details',
                summary: 'Outer',
                open: true,
                parts: [
                    { kind: 'text', text: 'before' },
                    { kind: 'details', summary: 'Details', open: false, parts: [{ kind: 'text', text: 'inner' }] },
                    { kind: 'text', text: 'after' },
                ],
            },
        ])
    })

    it('leaves a tag with no partner, or with attributes it would hide, as written', () => {
        expect(foldDetails('a <details> b')).toEqual([{ kind: 'text', text: 'a <details> b' }])
        expect(foldDetails('a </details> b')).toEqual([{ kind: 'text', text: 'a </details> b' }])
        const attributed = '<details title="x">body</details>'
        expect(foldDetails(attributed)).toEqual([{ kind: 'text', text: attributed }])
        // The unmatched opening tag stays text, and the block after it still folds.
        expect(foldDetails('<details>\n<details>x</details>')).toEqual([
            { kind: 'text', text: '<details>' },
            { kind: 'details', summary: 'Details', open: false, parts: [{ kind: 'text', text: 'x' }] },
        ])
    })

    it('reads text with no block as one part, unchanged', () => {
        expect(foldDetails('Rename this.\n\nIt reads better.')).toEqual([
            { kind: 'text', text: 'Rename this.\n\nIt reads better.' },
        ])
    })
})

describe('hidesText', () => {
    it('finds a hidden character in a block, its summary, or a block nested in it', () => {
        expect(hidesText(foldDetails('<details>\nplain\n</details>'))).toBe(false)
        expect(hidesText(foldDetails('<details>\nzero​width\n</details>'))).toBe(true)
        expect(hidesText(foldDetails('<details><summary>a‮b</summary>x</details>'))).toBe(true)
        expect(hidesText(foldDetails('<details>\n<details>\u{E0041}</details>\n</details>'))).toBe(true)
    })

    it('keeps a hidden character at either end of a summary, where trimming it would hide it', () => {
        const [block] = foldDetails('<details><summary> \uFEFFFix this\u2028 </summary>x</details>')
        expect(block).toMatchObject({ kind: 'details', summary: '\uFEFFFix this\u2028' })
        expect(foldDetails('<details><summary>\u2029</summary>x</details>')[0]).toMatchObject({ summary: '\u2029' })
        expect(hidesText(foldDetails('<details><summary>\uFEFFFix this</summary>x</details>'))).toBe(true)
    })
})
