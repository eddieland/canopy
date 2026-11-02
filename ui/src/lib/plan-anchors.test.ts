import { describe, expect, it } from 'vitest'

import { anchorAt, approximateMatches, collapse, CONTEXT, locate } from '@/lib/plan-anchors'
import type { Anchor, Match } from '@/lib/plan-anchors'

const PLAN = 'Add a CSV export.\nThe export streams rows.\n\nTest the export with a large report.'

function quoted(text: string, quote: string, from = 0) {
    const start = text.indexOf(quote, from)
    return anchorAt(text, start, start + quote.length)
}

describe('anchorAt', () => {
    it('keeps the passage and the text either side, whitespace collapsed', () => {
        expect(quoted(PLAN, 'streams rows')).toEqual({
            quote: 'streams rows',
            prefix: 'Add a CSV export. The export',
            suffix: '. Test the export with a large r',
        })
    })

    it('trims whitespace from the selection and refuses one of whitespace alone', () => {
        const start = PLAN.indexOf(' streams')
        expect(anchorAt(PLAN, start, start + 9)?.quote).toBe('streams')
        expect(anchorAt(PLAN, 17, 18)).toBeUndefined()
    })

    it('keeps at most CONTEXT characters either side', () => {
        const long = `${'a'.repeat(100)} middle ${'b'.repeat(100)}`
        const anchor = quoted(long, 'middle')
        expect(anchor?.prefix).toHaveLength(CONTEXT)
        expect(anchor?.suffix).toHaveLength(CONTEXT)
    })
})

describe('locate', () => {
    it('finds a passage again after text above it changed', () => {
        const anchor = quoted(PLAN, 'streams rows')
        if (!anchor) {
            throw new Error('no anchor')
        }
        const edited = `# Plan\n\n${PLAN}`
        const span = locate(edited, anchor)
        expect(span && edited.slice(span.start, span.end)).toBe('streams rows')
    })

    it('tells two copies apart by the text around them', () => {
        const second = PLAN.indexOf('the export', 20)
        const anchor = anchorAt(PLAN, second, second + 'the export'.length)
        if (!anchor) {
            throw new Error('no anchor')
        }
        expect(locate(PLAN, anchor)).toEqual({ start: second, end: second + 'the export'.length })
    })

    it('finds a passage the planner reflowed', () => {
        const anchor = quoted('one two three four', 'two three')
        if (!anchor) {
            throw new Error('no anchor')
        }
        const reflowed = 'one two\n   three four'
        const span = locate(reflowed, anchor)
        expect(span && collapse(reflowed.slice(span.start, span.end))).toBe('two three')
    })

    it('finds nothing for a passage that is gone, rather than something near it', () => {
        const anchor = quoted(PLAN, 'streams rows')
        if (!anchor) {
            throw new Error('no anchor')
        }
        expect(locate(PLAN.replace('streams rows', 'buffers rows'), anchor)).toBeUndefined()
        expect(locate(PLAN, { quote: '', prefix: '', suffix: '' })).toBeUndefined()
    })

    it('looks only for the exact words unless asked to look approximately', () => {
        expect(locate(PLAN.replace('streams rows', 'streams its rows'), anchored(PLAN, 'streams rows'))).toBeUndefined()
    })

    it('of exact copies that match alike, picks the one nearest where the passage was', () => {
        const block = `${'x'.repeat(40)}\nRetry the upload twice.\n`
        const text = block.repeat(4)
        const second = text.indexOf('Retry', block.length)
        const third = text.indexOf('Retry', second + 1)
        const anchor = anchored(text, 'Retry the upload twice', second)
        expect(locate(text, anchor, { near: third })?.start).toBe(third)
        expect(locate(text, anchor, { near: second + 5 })?.start).toBe(second)
        // With no place to be near, the first of them, the context either side of every copy the same.
        expect(locate(text, anchor)?.start).toBe(second - block.length)
    })
})

describe('locate, approximately', () => {
    const STEPS =
        'Add a CSV export.\nThe export streams rows to the browser as they are read.\n\n' +
        'Test the export with a large report.'
    const SENTENCE = 'The export streams rows to the browser as they are read.'

    it('finds a passage lightly reworded', () => {
        const anchor = anchored(PLAN, 'streams rows')
        expect(found(PLAN.replace('streams rows', 'streams its rows'), anchor)).toBe('streams its rows')
        expect(found(PLAN.replace('streams rows', 'streams\n rows'), anchor)).toBe('streams\n rows')
        const reworded = STEPS.replace(SENTENCE, 'The export streams the rows to the browser as it reads them.')
        expect(found(reworded, anchored(STEPS, SENTENCE))).toBe(
            'The export streams the rows to the browser as it reads them.',
        )
    })

    it('finds a long passage reworded with the text around it rewritten, since most of the anchor held', () => {
        const passage =
            'The export streams rows to the browser as they are read, so a large report never sits whole in memory, ' +
            'the page shows progress as each batch of rows arrives, and a reader who closes the tab stops the query ' +
            'rather than leave it running against the replica for nobody.'
        const before = `Add a CSV export.\n${passage}\n\nTest the export with a large report.`
        const reworded = passage
            .replace('streams rows', 'streams the rows')
            .replace('the page shows', 'the page then shows')
        const after = `# Exports\n\nOne format for now.\n${reworded}\n\nShip it behind a flag.`
        expect(found(after, anchored(before, passage))).toBe(reworded)
        // A short one with the same edits and the same new surroundings is gone: its words alone prove too little.
        const short = 'The export streams rows.'
        expect(
            found(`# Exports\n\nOne format for now.\nThe export streams the rows.\n\nShip it.`, anchored(PLAN, short)),
        ).toBeUndefined()
    })

    it('finds nothing for a passage rewritten or deleted', () => {
        const anchor = anchored(PLAN, 'streams rows')
        expect(found(PLAN.replace('streams rows', 'buffers rows'), anchor)).toBeUndefined()
        expect(found(PLAN.replace('streams rows', 'writes the whole file at once'), anchor)).toBeUndefined()
        expect(found(PLAN.replace(' streams rows', ''), anchor)).toBeUndefined()
        const sentence = anchored(STEPS, SENTENCE)
        expect(found(STEPS.replace(SENTENCE, 'Exports are written to disk in one go.'), sentence)).toBeUndefined()
        expect(found(STEPS.replace(`${SENTENCE}\n`, ''), sentence)).toBeUndefined()
    })

    it('moves a short passage only where the text around it held', () => {
        expect(found(PLAN.replace('CSV', 'TSV'), anchored(PLAN, 'CSV'))).toBe('TSV')
        expect(found(PLAN.replace('rows', 'row'), anchored(PLAN, 'rows'))).toBe('row')
        // `row` is there with one edit, but nothing around it is what was around `rows`.
        expect(found('Each row is a line of the file.', anchored(PLAN, 'rows'))).toBeUndefined()
        // Two letters swapped are two edits, one too many for three; dropping one is one, and the word is taken whole.
        expect(found(PLAN.replace('CSV', 'CVS'), anchored(PLAN, 'CSV'))).toBe('CVS')
        expect(found(PLAN.replace('CSV', 'XML'), anchored(PLAN, 'CSV'))).toBeUndefined()
    })

    it('keeps the exact words first, even where a reworded copy has the better context', () => {
        const anchor = anchored(PLAN, 'streams rows')
        const text = `${PLAN.replace('streams rows', 'streams its rows')}\n\nElsewhere, the job streams rows.`
        expect(found(text, anchor)).toBe('streams rows')
        expect(locate(text, anchor, { approximate: true })?.start).toBe(text.lastIndexOf('streams rows'))
    })

    it('of reworded copies that match alike, picks the one nearest where the passage was', () => {
        const block = `${'x'.repeat(40)}\nRetry the upload twice.\n`
        const text = block.repeat(4)
        const second = text.indexOf('Retry', block.length)
        const third = text.indexOf('Retry', second + 1)
        const anchor = anchored(text, 'Retry the upload twice', second)
        const reworded = text.replaceAll('twice', 'two times')
        const copies = [...reworded.matchAll(/Retry/gu)].map((match) => match.index)
        expect(locate(reworded, anchor, { approximate: true, near: second })?.start).toBe(copies[1])
        expect(locate(reworded, anchor, { approximate: true, near: third })?.start).toBe(copies[2])
    })

    it('stays a pass or two over a long plan, however long the passage', () => {
        const plan = longPlan(12_000)
        expect(plan.length).toBeGreaterThan(60_000)
        const start = plan.indexOf('.', 30_000) + 2
        const stop = plan.indexOf(' ', start + 150)
        const short = anchorAt(plan, start, stop)
        const long = anchorAt(plan, 1000, 1000 + 4000)
        if (!short || !long) {
            throw new Error('no anchor')
        }
        const begun = performance.now()
        expect(found(plan, { ...short, quote: `${short.quote} zebra` })).toBe(plan.slice(start, stop))
        expect(found(plan.replace(long.quote, long.quote.replaceAll(' the ', ' a ')), long)).toBeDefined()
        expect(found(plan, { quote: 'quartz walnut gazebo', prefix: '', suffix: '' })).toBeUndefined()
        // A short passage one edit from a word on every line: hundreds of near misses, of which only some are scored.
        expect(found(plan, { quote: 'exprt', prefix: 'quartz walnut gazebo', suffix: 'quartz' })).toBeUndefined()
        // A ceiling far above what this takes (tens of milliseconds), to catch work that grows with the passage's
        // length times the plan's, which takes seconds here; not to time it.
        expect(performance.now() - begun).toBeLessThan(2000)
    })
})

describe('approximateMatches', () => {
    it('finds where a pattern ends with at most so many edits', () => {
        expect(approximateMatches('the cat sat', 'cat', 0)).toEqual([{ end: 7, edits: 0 }])
        expect(approximateMatches('the cot sat', 'cat', 1).map((match) => match.end)).toEqual([7, 11])
        expect(approximateMatches('a cat', 'cat', 1, true)).toEqual([])
        expect(approximateMatches('cat', '', 1)).toEqual([])
    })

    it('agrees with the plain edit-distance table, for patterns of one word and of many', () => {
        let seed = 7
        const random = (n: number) => {
            seed = (seed * 1_103_515_245 + 12_345) % 2_147_483_648
            return seed % n
        }
        const draw = (letters: string, length: number) =>
            Array.from({ length }, () => letters[random(letters.length)] ?? '').join('')
        for (let round = 0; round < 600; round += 1) {
            const letters = 'abcd'.slice(0, 2 + random(3))
            const pattern = draw(letters, 1 + random(round % 3 === 0 ? 140 : 40))
            let text = draw(letters, random(300))
            if (random(2) === 0) {
                const at = random(text.length + 1)
                text = text.slice(0, at) + pattern + text.slice(at)
            }
            const max = random(pattern.length + 3)
            const fromStart = random(2) === 0
            expect(approximateMatches(text, pattern, max, fromStart), `round ${round}`).toEqual(
                slowMatches(text, pattern, max, fromStart),
            )
        }
    })
})

// The anchor for the first `quote` in `text` at or after `from`, which the test needs to be there.
function anchored(text: string, quote: string, from = 0): Anchor {
    const anchor = quoted(text, quote, from)
    if (!anchor) {
        throw new Error(`no ${quote} in the text`)
    }
    return anchor
}

// What of `text` `locate` finds for `anchor` looking approximately, or undefined when it finds nothing.
function found(text: string, anchor: Anchor): string | undefined {
    const span = locate(text, anchor, { approximate: true })
    return span && text.slice(span.start, span.end)
}

// A plan of `words` words drawn from a few dozen by a fixed sequence, in sentences and paragraphs: long, and as
// repetitive as prose, so a search over it meets many near misses.
function longPlan(words: number): string {
    const vocabulary = [
        ...'the export streams rows to a file and each worker reads its ticket before it writes code'.split(' '),
        ...'tests check that a report stays small while the planner keeps comments on passages'.split(' '),
    ]
    let seed = 1
    const out: string[] = []
    for (let i = 0; i < words; i += 1) {
        seed = (seed * 1_103_515_245 + 12_345) % 2_147_483_648
        out.push(vocabulary[seed % vocabulary.length] ?? 'word')
        if (i % 13 === 12) {
            out.push(i % 91 === 90 ? '.\n\n' : '.')
        }
    }
    return out.join(' ')
}

// Every place `pattern` ends in `text` with at most `max` edits, by the plain edit-distance table, column by column.
function slowMatches(text: string, pattern: string, max: number, fromStart: boolean): Match[] {
    let column = Array.from({ length: pattern.length + 1 }, (_, i) => i)
    const matches: Match[] = []
    for (let j = 1; j <= text.length; j += 1) {
        const next = [fromStart ? j : 0]
        for (let i = 1; i <= pattern.length; i += 1) {
            const change = (column[i - 1] ?? 0) + (pattern[i - 1] === text[j - 1] ? 0 : 1)
            next.push(Math.min(change, (column[i] ?? 0) + 1, (next[i - 1] ?? 0) + 1))
        }
        column = next
        const edits = column[pattern.length] ?? 0
        if (edits <= max) {
            matches.push({ end: j, edits })
        }
    }
    return matches
}
