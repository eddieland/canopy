import { describe, expect, it } from 'vitest'

import type { DiffFile, DiffLine } from '@/api/types'

import { changedWords, fileLines, hunkRange, lineParts } from './diff-words'

/** A file of one hunk whose lines are written as git prints them, each led by its `+`, `-`, or space. */
function file(...written: string[]): DiffFile {
    let old = 0
    let now = 0
    const lines = written.map((text): DiffLine => {
        const kind = text.startsWith('+') ? 'add' : text.startsWith('-') ? 'del' : 'ctx'
        old += kind === 'add' ? 0 : 1
        now += kind === 'del' ? 0 : 1
        return { kind, old: kind === 'add' ? null : old, new: kind === 'del' ? null : now, text: text.slice(1) }
    })
    return { path: 'a.ts', old_path: null, binary: false, hunks: [{ header: '', lines }] }
}

/** The words marked on each line of the file's one hunk, null for a line with none. */
function marked(diff: DiffFile): (string[] | null)[] {
    const lines = diff.hunks[0]?.lines ?? []
    return (changedWords(diff)[0] ?? []).map((changed, i) =>
        changed === undefined || changed.length === 0
            ? null
            : changed.map(({ from, to }) => lines[i]?.text.slice(from, to) ?? ''),
    )
}

describe('changedWords', () => {
    it('marks the whole words that differ between a removed line and the one that replaced it', () => {
        expect(marked(file(' a', '-    run(onSearch(value))', '+    run(search(value))'))).toEqual([
            null,
            ['onSearch'],
            ['search'],
        ])
    })

    it('marks each of two edits to a line, and leaves what is between them', () => {
        expect(marked(file('-const wait = send(query, 250)', '+let wait = send(query, WAIT_MS)'))).toEqual([
            ['const', '250'],
            ['let', 'WAIT_MS'],
        ])
    })

    it('marks a phrase rewritten as one stretch, its spaces with it', () => {
        expect(marked(file('-return the first value here', '+return a second value here'))).toEqual([
            ['the first'],
            ['a second'],
        ])
    })

    it('pairs a removed line with the added line like it, past one that was only added', () => {
        expect(
            marked(file('-return send(query, 250)', '+const wait = useWait()', '+return send(query, wait)')),
        ).toEqual([['250'], null, ['wait']])
    })

    it('leaves a line replaced by an unlike one to its own tint', () => {
        expect(marked(file('-    const a = first(x)', '+    return other.thing(x)'))).toEqual([null, null])
    })

    it('marks only the added side when the new line only adds to the old', () => {
        expect(marked(file('-call(a)', '+call(a, b)'))).toEqual([null, [', b']])
    })

    it('marks nothing on a line only moved in or out, and only the edit on one edited as it moved', () => {
        expect(
            marked(file('-run(query)', '-    .then(read)', '+    run(query, signal)', '+        .then(read)')),
        ).toEqual([null, null, [', signal'], null])
    })

    it('marks nothing on lines with no pair', () => {
        expect(marked(file('+one', '+two', ' three', '-four'))).toEqual([null, null, null, null])
    })

    it('never cuts a character written as two code units', () => {
        expect(marked(file('-say("😀 hello there")', '+say("😃 hello there")'))).toEqual([['😀'], ['😃']])
    })
})

describe('hunkRange', () => {
    it("writes each side's first line and how many it has, as git does", () => {
        const [hunk] = file(' a', '-b', '+c', '+d').hunks
        expect(hunk && hunkRange(hunk)).toBe('-1,2 +1,3')
    })

    it('writes a side with no lines as git does', () => {
        const [hunk] = file('+a', '+b').hunks
        expect(hunk && hunkRange(hunk)).toBe('-0,0 +1,2')
    })
})

describe('fileLines', () => {
    it("counts a file's added and removed lines", () => {
        expect(fileLines(file(' a', '-b', '+c', '+d'))).toEqual({ added: 2, removed: 1 })
    })
})

describe('lineParts', () => {
    it("cuts a line's tokens at the changed stretch, each piece keeping its kind", () => {
        const parts = lineParts(
            'return search(value)',
            [
                { kind: 'keyword', text: 'return' },
                { kind: 'text', text: ' ' },
                { kind: 'function', text: 'search' },
                { kind: 'text', text: '(value)' },
            ],
            [{ from: 7, to: 15 }],
        )
        expect(parts.map((part) => [part.changed, part.text])).toEqual([
            [false, 'return '],
            [true, 'search(v'],
            [false, 'alue)'],
        ])
        expect(parts[1]?.tokens).toEqual([
            { kind: 'function', text: 'search' },
            { kind: 'text', text: '(v' },
        ])
    })

    it('spells a line with no tokens as its text, each stretch marked, and leaves out an empty end', () => {
        expect(
            lineParts('abcde', undefined, [
                { from: 0, to: 2 },
                { from: 3, to: 4 },
            ]),
        ).toEqual([
            { changed: true, text: 'ab', tokens: undefined },
            { changed: false, text: 'c', tokens: undefined },
            { changed: true, text: 'd', tokens: undefined },
            { changed: false, text: 'e', tokens: undefined },
        ])
    })
})
