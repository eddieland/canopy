import { describe, expect, it } from 'vitest'

import { applyEdit, continueList, toggleCodeBlock, toggleLinePrefix, toggleMark } from './markdown-edit'
import type { Edit } from './markdown-edit'

// Text with its selection written in it, `[` and `]` around a selection or `|` for a cursor, and back.
function at(marked: string): { text: string; selection: { start: number; end: number } } {
    const cursor = marked.indexOf('|')
    if (cursor !== -1) {
        return { text: marked.replace('|', ''), selection: { start: cursor, end: cursor } }
    }
    const start = marked.indexOf('[')
    const end = marked.indexOf(']') - 1
    return { text: marked.replace('[', '').replace(']', ''), selection: { start, end } }
}

function shown(text: string, edit: Edit | undefined): string {
    if (edit === undefined) {
        return 'no edit'
    }
    const after = applyEdit(text, edit)
    const { start, end } = edit.selection
    if (start === end) {
        return `${after.slice(0, start)}|${after.slice(start)}`
    }
    return `${after.slice(0, start)}[${after.slice(start, end)}]${after.slice(end)}`
}

function run(marked: string, edit: (text: string, selection: { start: number; end: number }) => Edit | undefined) {
    const { text, selection } = at(marked)
    return shown(text, edit(text, selection))
}

describe('toggleMark', () => {
    it('marks a selection strong, and unmarks it from inside or out', () => {
        expect(run('use [the v2 API] now', (t, s) => toggleMark(t, s, 'strong'))).toBe('use **[the v2 API]** now')
        expect(run('use **[the v2 API]** now', (t, s) => toggleMark(t, s, 'strong'))).toBe('use [the v2 API] now')
        expect(run('use [**the v2 API**] now', (t, s) => toggleMark(t, s, 'strong'))).toBe('use [the v2 API] now')
    })

    it('leaves the whitespace at a selection’s ends outside its markers', () => {
        expect(run('run [tests ]now', (t, s) => toggleMark(t, s, 'code'))).toBe('run `[tests]` now')
    })

    it('gives a cursor an empty pair to type in, and takes one back', () => {
        expect(run('see |', (t, s) => toggleMark(t, s, 'code'))).toBe('see `|`')
        expect(run('see **|**', (t, s) => toggleMark(t, s, 'strong'))).toBe('see |')
    })

    it('fences code over several lines as a block', () => {
        expect(run('[a\nb]', (t, s) => toggleMark(t, s, 'code'))).toBe('```\n[a\nb]\n```')
    })
})

describe('toggleCodeBlock', () => {
    it('fences the selection’s whole lines, and unfences them', () => {
        expect(run('intro\nmake [te]st\nend', toggleCodeBlock)).toBe('intro\n```\n[make test]\n```\nend')
        expect(run('intro\n```\nmake [te]st\n```\nend', toggleCodeBlock)).toBe('intro\n[make test]\nend')
    })

    it('opens an empty block with the cursor inside', () => {
        expect(run('|', toggleCodeBlock)).toBe('```\n|\n```')
    })
})

describe('toggleLinePrefix', () => {
    it('starts a line with a bullet and keeps the cursor in its words, then takes it off', () => {
        expect(run('fix t|he test', (t, s) => toggleLinePrefix(t, s, 'bullet'))).toBe('- fix t|he test')
        expect(run('- fix t|he test', (t, s) => toggleLinePrefix(t, s, 'bullet'))).toBe('fix t|he test')
    })

    it('numbers the lines selected, past a blank one, in place of their bullets', () => {
        const text = '[- one\n\n- two\nthree]'
        expect(run(text, (t, s) => toggleLinePrefix(t, s, 'ordered'))).toBe('[1. one\n\n2. two\n3. three]')
    })

    it('makes a list item a heading, keeping its indent', () => {
        expect(run('  - Plan|', (t, s) => toggleLinePrefix(t, s, 'heading'))).toBe('  ## Plan|')
    })
})

describe('continueList', () => {
    it('starts the next item, numbered on from the last', () => {
        expect(run('- one|', continueList)).toBe('- one\n- |')
        expect(run('  3) three|', continueList)).toBe('  3) three\n  4) |')
    })

    it('ends the list on an empty item', () => {
        expect(run('- one\n- |', continueList)).toBe('- one\n|')
    })

    it('leaves Enter alone outside a list, before an item’s marker, in code, and over a selection', () => {
        expect(run('plain|', continueList)).toBe('no edit')
        expect(run('2026.|', continueList)).toBe('no edit')
        expect(run('|- one', continueList)).toBe('no edit')
        expect(run('```\n- one|', continueList)).toBe('no edit')
        expect(run('- [one]', continueList)).toBe('no edit')
    })
})
