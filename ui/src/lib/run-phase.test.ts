import { describe, expect, it } from 'vitest'

import { DEFAULT, parseQuips, PHASE_WORD, QUIPS, runPhase } from './run-phase'
import type { RunPhase } from './run-phase'

// The words each phase's quips may name it by, so a quip in the plain word's place still says what the run does.
const NAMES: Record<RunPhase, RegExp> = {
    plan: /plan/u,
    'feedback-plan': /plan/u,
    implement: /implement|cod|build/u,
    resume: /resum/u,
    ci: /CI/u,
    review: /review/u,
    reply: /reply/u,
    conflict: /conflict/u,
    no_pr: /PR/u,
    retarget: /retarget|base/u,
    split: /split/u,
    'needs-plan': /triag/u,
}

function run(kind: string, reasons: string[] = [], ticketKey = 'ABC-101') {
    return { ticket_key: ticketKey, kind, reasons }
}

describe('runPhase', () => {
    it('says each kind in plain words, a retired one as the phase that replaced it', () => {
        expect(runPhase(run('plan')).word).toBe('planning')
        expect(runPhase(run('implement')).word).toBe('implementing')
        expect(runPhase(run('fix-ci')).word).toBe('fixing CI')
        expect(runPhase(run('resume')).word).toBe('resuming')
    })

    it("says a resume as its reasons, and its quip as the first's, with how many more", () => {
        const doing = runPhase(run('resume', ['ci', 'review']))
        expect(doing.word).toBe('fixing CI, addressing review')
        expect(QUIPS.ci.some((quip) => doing.quip === `${quip} +1`)).toBe(true)
    })

    it('says a kind it does not know as itself, with no quip', () => {
        expect(runPhase(run('dance'))).toEqual({ word: 'dance', quip: null })
    })

    it('picks the same quip for a ticket and a phase every time', () => {
        expect(runPhase(run('plan', [], 'ABC-7'))).toEqual(runPhase(run('plan', [], 'ABC-7')))
    })

    it('picks from across the quips, ticket by ticket', () => {
        const picked = new Set(Array.from({ length: 200 }, (_, n) => runPhase(run('implement', [], `ABC-${n}`)).quip))
        expect(picked).toEqual(new Set(QUIPS.implement))
    })
})

describe('QUIPS', () => {
    it("names each phase in a word the operator knows, short enough for the rail's line", () => {
        for (const [phase, quips] of Object.entries(QUIPS) as [RunPhase, readonly string[]][]) {
            expect(quips.length).toBeGreaterThanOrEqual(2)
            for (const quip of quips) {
                expect(quip).toMatch(NAMES[phase])
                expect(quip.length).toBeLessThanOrEqual(24)
            }
        }
    })

    it('never says the same thing for two phases', () => {
        const all = Object.values(QUIPS).flat()
        expect(new Set(all).size).toBe(all.length)
    })

    it('never repeats a plain word as a quip of another phase', () => {
        for (const [phase, word] of Object.entries(PHASE_WORD) as [RunPhase, string][]) {
            const others = Object.entries(QUIPS).filter(([other]) => other !== phase)
            expect(others.flatMap(([, quips]) => quips)).not.toContain(word)
        }
    })
})

describe('parseQuips', () => {
    it('is on unless turned off', () => {
        expect(DEFAULT).toBe('on')
        expect(parseQuips(null)).toBe('on')
        expect(parseQuips('off')).toBe('off')
        expect(parseQuips('maybe')).toBe('on')
    })
})
