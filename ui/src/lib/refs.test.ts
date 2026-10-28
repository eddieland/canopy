import { describe, expect, it } from 'vitest'

import {
    choreRef,
    choreRunRef,
    feedbackPlanRef,
    memoryRef,
    messageRef,
    parseTaskRef,
    planRef,
    reviewRef,
    runRef,
    slotRef,
    splitRunRefs,
    tickRef,
} from './refs'

describe('refs', () => {
    it('names each kind as KIND:ID, the grammar the CLI reads', () => {
        expect(runRef(41)).toBe('run:41')
        expect(reviewRef(4)).toBe('review:4')
        expect(tickRef(2)).toBe('tick:2')
        expect(memoryRef(3)).toBe('memory:3')
        expect(choreRef('deps')).toBe('chore:deps')
        expect(planRef(2)).toBe('plan:2')
        expect(feedbackPlanRef(7)).toBe('feedback-plan:7')
    })

    it("names a chore run by its chore's reference and its number", () => {
        expect(choreRunRef('deps', 2)).toBe('chore:deps#2')
        expect(choreRunRef('deps', '2')).toBe('chore:deps#2')
    })

    it('numbers a message and a slot as their lists do', () => {
        expect(messageRef(5)).toBe('#5')
        expect(slotRef('3')).toBe('#3')
    })
})

describe('parseTaskRef', () => {
    it("reads a task's reference alone, as the CLI reads it", () => {
        expect(parseTaskRef('task:4')).toBe(4)
        expect(parseTaskRef('  task:004 ')).toBe(4)
        for (const text of ['task:0', 'task:', 'task:4 csv', 'Task:4', 'run:4', 'task:-4', 'task:4.5', 'task:1e3']) {
            expect(parseTaskRef(text)).toBeUndefined()
        }
    })
})

describe('splitRunRefs', () => {
    it('splits harness text around each run it names, standing as a word of its own', () => {
        expect(splitRunRefs('run:40 (fix-ci) ended failed; see run:39.')).toEqual([
            { text: 'run:40', run: 40 },
            { text: ' (fix-ci) ended failed; see ' },
            { text: 'run:39', run: 39 },
            { text: '.' },
        ])
        expect(splitRunRefs('rerun:4 and run:x')).toEqual([{ text: 'rerun:4 and run:x' }])
        expect(splitRunRefs('')).toEqual([])
    })
})
