import { describe, expect, it } from 'vitest'

import type { AgentInstructions } from '@/api/types'

import { fileName, instructionsLine, instructionsState, savedBytes, unsavedClause } from './instructions'

function file(over: Partial<AgentInstructions> = {}): AgentInstructions {
    return {
        agent: 'worker',
        key: 'paths.worker_instructions',
        path: '/home/me/worker.md',
        text: 'Run the linters.\n',
        sha256: 'aaa',
        problem: null,
        missing: false,
        ...over,
    }
}

describe('instructionsState', () => {
    it('tells a file read as it is from none, a missing one, and one a run would refuse', () => {
        expect(instructionsState(file())).toBe('set')
        expect(instructionsState(file({ path: null, text: null, sha256: null }))).toBe('none')
        expect(instructionsState(file({ text: null, sha256: null, problem: 'missing: …', missing: true }))).toBe(
            'missing',
        )
        expect(instructionsState(file({ problem: '5000 bytes, over the 4096 a run takes' }))).toBe('refused')
    })
})

describe('instructionsLine', () => {
    it('counts the agents that hear instructions, then the files missing and refused, each left out at none', () => {
        const none = file({ path: null, text: null, sha256: null })
        expect(instructionsLine([file(), none, none, none])).toBe('1 of 4 agents hear standing instructions')
        expect(
            instructionsLine([
                file(),
                file({ missing: true, problem: 'missing', text: null, sha256: null }),
                file({ problem: 'not UTF-8' }),
                file({ problem: 'not UTF-8' }),
            ]),
        ).toBe('1 of 4 agents hear standing instructions · 1 file missing · 2 files a run would refuse')
    })
})

describe('unsavedClause', () => {
    it('names every agent with an edit not saved, in a list a sentence can hold', () => {
        expect(unsavedClause(['Worker'])).toBe('your edits to the worker instructions are not saved')
        expect(unsavedClause(['Worker', 'Overseer', 'Chores'])).toBe(
            'your edits to the worker, overseer, and chores instructions are not saved',
        )
    })
})

describe('savedBytes', () => {
    it('counts UTF-8 bytes, as a run does, not characters', () => {
        expect(savedBytes('…\n')).toBe(4)
    })

    it('counts the newline a save adds to a last line left open, and none for empty text', () => {
        expect(savedBytes('Run the linters.')).toBe(17)
        expect(savedBytes('Run the linters.\n')).toBe(17)
        expect(savedBytes('')).toBe(0)
    })
})

describe('fileName', () => {
    it('is the last part of the path', () => {
        expect(fileName('/home/me/.config/canopy/worker.md')).toBe('worker.md')
    })
})
