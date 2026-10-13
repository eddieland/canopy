import { describe, expect, it } from 'vitest'

import { jsonLines, tokenize } from '@/lib/json-lines'

describe('tokenize', () => {
    it('splits a JSON line into keys, strings, numbers, literals, and punctuation, as written', () => {
        expect(tokenize('{"a": "b:c", "n": -1.5e3, "ok": true, "x": [null]}')).toEqual([
            { kind: 'punct', text: '{' },
            { kind: 'key', text: '"a"' },
            { kind: 'punct', text: ':' },
            { kind: 'text', text: ' ' },
            { kind: 'string', text: '"b:c"' },
            { kind: 'punct', text: ',' },
            { kind: 'text', text: ' ' },
            { kind: 'key', text: '"n"' },
            { kind: 'punct', text: ':' },
            { kind: 'text', text: ' ' },
            { kind: 'number', text: '-1.5e3' },
            { kind: 'punct', text: ',' },
            { kind: 'text', text: ' ' },
            { kind: 'key', text: '"ok"' },
            { kind: 'punct', text: ':' },
            { kind: 'text', text: ' ' },
            { kind: 'literal', text: 'true' },
            { kind: 'punct', text: ',' },
            { kind: 'text', text: ' ' },
            { kind: 'key', text: '"x"' },
            { kind: 'punct', text: ':' },
            { kind: 'text', text: ' ' },
            { kind: 'punct', text: '[' },
            { kind: 'literal', text: 'null' },
            { kind: 'punct', text: ']' },
            { kind: 'punct', text: '}' },
        ])
    })

    it('reads escaped quotes inside a string, and a string that ends in a colon is not a key', () => {
        expect(tokenize('["say \\"hi\\"", "k:"]').map((t) => t.kind)).toEqual([
            'punct',
            'string',
            'punct',
            'text',
            'string',
            'punct',
        ])
        expect(tokenize('{"k": "v"}  ').at(-1)).toEqual({ kind: 'text', text: '  ' })
    })

    it('leaves any other line whole: log lines, bare JSON values, and JSON that does not parse', () => {
        const log = 'WARN  2026-10-08T11:00:01 +1043ms service=mcp key=jira error={"a": 1}'
        expect(tokenize(log)).toEqual([{ kind: 'text', text: log }])
        expect(tokenize('42')).toEqual([{ kind: 'text', text: '42' }])
        expect(tokenize('{"cut": "the line ends')).toEqual([{ kind: 'text', text: '{"cut": "the line ends' }])
        expect(tokenize('')).toEqual([])
    })

    it('keeps every character, so the tokens joined are the line', () => {
        const line = '{"type":"text","part":{"text":"a \\\\ b \\u00e9","n":[1,2.0,-3]}}'
        expect(
            tokenize(line)
                .map((t) => t.text)
                .join(''),
        ).toBe(line)
    })

    it('splits a block of indented JSON across its lines, and leaves a cut one whole', () => {
        const block = '{\n  "filePath": "a.ts",\n  "limit": 20\n}'
        expect(tokenize(block)).toEqual([
            { kind: 'punct', text: '{' },
            { kind: 'text', text: '\n  ' },
            { kind: 'key', text: '"filePath"' },
            { kind: 'punct', text: ':' },
            { kind: 'text', text: ' ' },
            { kind: 'string', text: '"a.ts"' },
            { kind: 'punct', text: ',' },
            { kind: 'text', text: '\n  ' },
            { kind: 'key', text: '"limit"' },
            { kind: 'punct', text: ':' },
            { kind: 'text', text: ' ' },
            { kind: 'number', text: '20' },
            { kind: 'text', text: '\n' },
            { kind: 'punct', text: '}' },
        ])
        expect(tokenize('{\n  "filePath": "a.t')).toEqual([{ kind: 'text', text: '{\n  "filePath": "a.t' }])
    })
})

describe('jsonLines', () => {
    it('tokenizes each line on its own', () => {
        expect(jsonLines('{"a":1}\n--- stderr ---\n')).toEqual([
            [
                { kind: 'punct', text: '{' },
                { kind: 'key', text: '"a"' },
                { kind: 'punct', text: ':' },
                { kind: 'number', text: '1' },
                { kind: 'punct', text: '}' },
            ],
            [{ kind: 'text', text: '--- stderr ---' }],
            [],
        ])
    })
})
