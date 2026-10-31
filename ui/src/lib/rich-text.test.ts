import { describe, expect, it } from 'vitest'

import { WRAP, clamp, codeSpans, inline, lineCount, parse } from '@/lib/rich-text'
import type { Block } from '@/lib/rich-text'

const text = (value: string) => ({ kind: 'text', text: value })
// Ten-character words, so a line of `WRAP` characters holds nine of them with their spaces.
const words = (count: number) => Array.from({ length: count }, (_, i) => `word${String(i).padStart(6, '0')}`)

describe('parse', () => {
    it('keeps a paragraph its line breaks and splits paragraphs on a blank line', () => {
        expect(parse('Moved billing.\nRemoved v1.\n\nDone.')).toEqual([
            { kind: 'paragraph', lines: [[text('Moved billing.')], [text('Removed v1.')]] },
            { kind: 'paragraph', lines: [[text('Done.')]] },
        ])
    })

    it('reads bullets and numbers as lists, nested by indent, with a continued item', () => {
        expect(parse('Changes:\n- one\n  - two\n    still two\n* three')).toEqual([
            { kind: 'paragraph', lines: [[text('Changes:')]] },
            {
                kind: 'list',
                ordered: false,
                start: 1,
                items: [
                    { depth: 0, lines: [[text('one')]] },
                    { depth: 1, lines: [[text('two')], [text('still two')]] },
                    { depth: 0, lines: [[text('three')]] },
                ],
            },
        ])
        expect(parse('3. c\n4) d')).toEqual([
            {
                kind: 'list',
                ordered: true,
                start: 3,
                items: [
                    { depth: 0, lines: [[text('c')]] },
                    { depth: 0, lines: [[text('d')]] },
                ],
            },
        ])
    })

    it('starts a list of its own for a nested list of the other kind', () => {
        const blocks = parse('1. step\n   - detail')
        expect(blocks.map((b) => b.kind === 'list' && [b.ordered, b.items[0]?.depth])).toEqual([
            [true, 0],
            [false, 1],
        ])
    })

    it('keeps a fenced block verbatim, and an unclosed fence runs to the end', () => {
        expect(parse('Ran:\n```sh\nmake  check\n- not a list\n```\nafter')).toEqual([
            { kind: 'paragraph', lines: [[text('Ran:')]] },
            { kind: 'code', lines: ['make  check', '- not a list'], lang: 'sh' },
            { kind: 'paragraph', lines: [[text('after')]] },
        ])
        expect(parse('```\n**not strong**')).toEqual([{ kind: 'code', lines: ['**not strong**'] }])
    })

    it("names a fenced block's language by the first word after its fence, and none for a bare fence", () => {
        expect(parse('```toml examples/config.toml\na = 1\n```')).toEqual([
            { kind: 'code', lines: ['a = 1'], lang: 'toml' },
        ])
        expect(parse('~~~ python\nx\n~~~')).toEqual([{ kind: 'code', lines: ['x'], lang: 'python' }])
        expect(parse('```\nx\n```')[0]).not.toHaveProperty('lang')
    })

    it('reads a heading as one line', () => {
        expect(parse('## Summary\nok')).toEqual([
            { kind: 'heading', level: 2, line: [text('Summary')] },
            { kind: 'paragraph', lines: [[text('ok')]] },
        ])
    })

    it('reads carriage returns as line breaks and an empty text as nothing', () => {
        expect(parse('a\r\nb')).toEqual([{ kind: 'paragraph', lines: [[text('a')], [text('b')]] }])
        expect(parse('')).toEqual([])
    })

    it('reads a quote as its own blocks, nested by `>`, and ends it at a line without one', () => {
        expect(parse('> Retried twice.\n> - flaky\n>\n> > older\nafter')).toEqual([
            {
                kind: 'quote',
                blocks: [
                    { kind: 'paragraph', lines: [[text('Retried twice.')]] },
                    { kind: 'list', ordered: false, start: 1, items: [{ depth: 0, lines: [[text('flaky')]] }] },
                    { kind: 'quote', blocks: [{ kind: 'paragraph', lines: [[text('older')]] }] },
                ],
            },
            { kind: 'paragraph', lines: [[text('after')]] },
        ])
    })

    it('keeps the `>` of a quote nested past three as characters', () => {
        const innermost = (blocks: Block[]): Block | undefined => {
            const [first] = blocks
            return first?.kind === 'quote' ? innermost(first.blocks) : first
        }
        expect(innermost(parse('> > > > deep'))).toEqual({ kind: 'paragraph', lines: [[text('> deep')]] })
    })

    it('reads `---`, `***`, and `___` as a rule, one under a paragraph or among list items included', () => {
        expect(parse('one\n---\n- a\n* * *\n__ _').map((block) => block.kind)).toEqual([
            'paragraph',
            'rule',
            'list',
            'rule',
            'rule',
        ])
        expect(parse('-- not a rule')).toEqual([{ kind: 'paragraph', lines: [[text('-- not a rule')]] }])
    })

    it('reads a table, its columns aligned by their colons, its rows cut or padded to the head', () => {
        const table = [
            'Check | Result | Time | Note',
            ':--- | :---: | ---: | ---',
            '`lint` | **ok** | 4s',
            '| a | b | c | d | e |',
        ]
        expect(parse(`Ran:\n${table.join('\n')}\nafter`)).toEqual([
            { kind: 'paragraph', lines: [[text('Ran:')]] },
            {
                kind: 'table',
                align: ['left', 'center', 'right', undefined],
                head: [[text('Check')], [text('Result')], [text('Time')], [text('Note')]],
                rows: [
                    [[{ kind: 'code', text: 'lint' }], [{ kind: 'strong', text: 'ok' }], [text('4s')], []],
                    [[text('a')], [text('b')], [text('c')], [text('d')]],
                ],
            },
            { kind: 'paragraph', lines: [[text('after')]] },
        ])
    })

    it('keeps an escaped pipe in its cell, and reads no table without a matching delimiter row', () => {
        expect(parse('| a \\| b | c |\n|---|---|')).toEqual([
            { kind: 'table', align: [undefined, undefined], head: [[text('a | b')], [text('c')]], rows: [] },
        ])
        expect(parse('a | b\n|---|').map((block) => block.kind)).toEqual(['paragraph'])
        expect(parse('a | b\n---').map((block) => block.kind)).toEqual(['paragraph', 'rule'])
    })

    it('leaves markup it does not read as text', () => {
        expect(parse('<b>hi</b> [link](https://example.test)')).toEqual([
            { kind: 'paragraph', lines: [[text('<b>hi</b> [link](https://example.test)')]] },
        ])
    })
})

describe('codeSpans', () => {
    it('reads code spans alone, leaving asterisks as written', () => {
        expect(codeSpans('run `canopy workspace sync`, **then** wait')).toEqual([
            text('run '),
            { kind: 'code', text: 'canopy workspace sync' },
            text(', **then** wait'),
        ])
    })

    it('never carries a span across a line', () => {
        expect(codeSpans('a `b\nc` d')).toEqual([text('a `b\nc` d')])
    })
})

describe('inline', () => {
    it('reads code spans and strong runs', () => {
        expect(inline('ran `make check`, **all green**.')).toEqual([
            text('ran '),
            { kind: 'code', text: 'make check' },
            text(', '),
            { kind: 'strong', text: 'all green' },
            text('.'),
        ])
    })

    it('leaves an unclosed marker as written', () => {
        expect(inline('a `b and **c')).toEqual([text('a `b and **c')])
    })

    it('reads emphasis with either marker, and struck runs', () => {
        expect(inline('*not* merged, _yet_; ~~v1~~ gone')).toEqual([
            { kind: 'em', text: 'not' },
            text(' merged, '),
            { kind: 'em', text: 'yet' },
            text('; '),
            { kind: 'del', text: 'v1' },
            text(' gone'),
        ])
    })

    it('keeps an emphasis or struck marker inside a URL as text, so the URL links whole', () => {
        for (const written of [
            'see https://ci.example.test/_a_/b',
            'at https://x.test/~~old~~/new',
            'https://x.test/*a*',
        ]) {
            expect(inline(written)).toEqual([text(written)])
        }
        expect(inline('*see https://ci.example.test/7*')).toEqual([
            { kind: 'em', text: 'see https://ci.example.test/7' },
        ])
    })

    it('reads the code spans inside a run as code within it', () => {
        expect(inline('**bold around `code` inside** and **`name`**')).toEqual([
            { kind: 'strong', text: 'bold around ' },
            { kind: 'code', text: 'code', within: 'strong' },
            { kind: 'strong', text: ' inside' },
            text(' and '),
            { kind: 'code', text: 'name', within: 'strong' },
        ])
        expect(inline('*the `api` service* is ~~`v1`~~')).toEqual([
            { kind: 'em', text: 'the ' },
            { kind: 'code', text: 'api', within: 'em' },
            { kind: 'em', text: ' service' },
            text(' is '),
            { kind: 'code', text: 'v1', within: 'del' },
        ])
    })

    it('keeps an unclosed backtick inside a run as written', () => {
        expect(inline('**a `b**')).toEqual([{ kind: 'strong', text: 'a `b' }])
    })

    it('reads a code span before a run, as CommonMark does, so markers inside code are code', () => {
        expect(inline('**a `b** c`')).toEqual([text('**a '), { kind: 'code', text: 'b** c' }])
        expect(inline('`**` and **`**`**, `_x_`')).toEqual([
            { kind: 'code', text: '**' },
            text(' and '),
            { kind: 'code', text: '**', within: 'strong' },
            text(', '),
            { kind: 'code', text: '_x_' },
        ])
    })

    it('leaves a marker inside a word or beside a space as written', () => {
        for (const written of ['snake_case_name', '__init__', '2*3*4', 'a * b * c', '_ spaced _', '~~ spaced ~~']) {
            expect(inline(written)).toEqual([text(written)])
        }
    })
})

describe('clamp', () => {
    const blocks = parse('one\ntwo\n- three\n- four\n```\nfive\nsix\n```')

    it('counts each line, a list item and a code line included', () => {
        expect(lineCount(blocks)).toBe(6)
    })

    it('shows the first lines and says how many are left out', () => {
        const cut = clamp(blocks, 3)
        expect(cut.hidden).toBe(3)
        expect(lineCount(cut.blocks)).toBe(3)
        expect(cut.blocks.map((b) => b.kind)).toEqual(['paragraph', 'list'])
    })

    it('counts a table by its rows and a quote by its lines, and cuts each within the lines it shows', () => {
        const table = parse('a | b\n--|--\n1 | 2\n3 | 4\n5 | 6')
        expect(lineCount(table)).toBe(4)
        expect(clamp(table, 2).blocks).toEqual([{ ...table[0], rows: [[[text('1')], [text('2')]]] }])
        const quote = parse('> one\n> two\n> three\n\n---')
        expect(lineCount(quote)).toBe(4)
        expect(clamp(quote, 2).blocks).toEqual([
            { kind: 'quote', blocks: [{ kind: 'paragraph', lines: [[text('one')], [text('two')]] }] },
        ])
    })

    it('shows text one line over whole', () => {
        expect(clamp(blocks, 5)).toEqual({ blocks, hidden: 0 })
        expect(clamp(blocks, 6)).toEqual({ blocks, hidden: 0 })
    })

    it('counts a long line as the lines it wraps to, and a code line as one, since it scrolls', () => {
        expect(lineCount(parse(words(35).join(' ')))).toBe(Math.ceil((35 * 10 + 34) / WRAP))
        expect(lineCount(parse(`- ${words(25).join(' ')}\n- short`))).toBe(4)
        expect(lineCount(parse(`\`\`\`\n${'x'.repeat(3 * WRAP)}\n\`\`\``))).toBe(1)
    })

    it('cuts a long paragraph where a word ends, with an ellipsis, within the lines it shows', () => {
        const cut = clamp(parse(`${words(60).join(' ')}\n\nAfter.`), 2)
        expect(cut.hidden).toBe(6)
        expect(cut.blocks).toEqual([{ kind: 'paragraph', lines: [[text(words(18).join(' ')), text('…')]] }])
        expect(lineCount(cut.blocks)).toBe(2)
    })

    it('leaves out a piece it would cut mid-word, so a URL never links somewhere else', () => {
        const url = `https://ci.example.test/${'a'.repeat(WRAP)}`
        const cut = clamp(parse(`${words(5).join(' ')} \`code\` ${url}\n${words(40).join(' ')}`), 1)
        expect(cut.blocks).toEqual([
            {
                kind: 'paragraph',
                lines: [[text(`${words(5).join(' ')} `), { kind: 'code', text: 'code' }, text('…')]],
            },
        ])
    })
})
