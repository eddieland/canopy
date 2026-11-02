import { Editor } from '@tiptap/core'
import { describe, expect, it } from 'vitest'

import { decisionAnswers, MAX_QUESTION, planDecisions } from '@/lib/plan-decisions'
import type { PlanDecision } from '@/lib/plan-decisions'
import { planExtensions } from '@/lib/plan-schema'

const PLAN = [
    '# Plan: ABC-1 Schedule exports',
    '',
    '## Goal',
    '',
    'Exports on a schedule.',
    '',
    '## Decisions',
    '',
    "### Decision 1: Where a schedule's hour is kept",
    '',
    "- **A (chosen):** In the owner's timezone: the ticket asks for the owner's hour.",
    '- **B:** In UTC: simpler to store, but the hour moves when the clocks change.',
    '',
    '### Decision 2: What the email carries',
    '',
    '- **A:** The file itself: one click, but a large export bounces.',
    '- **B (chosen):** A link to the file, `/exports/:id`, which works for seven days.',
    '- **C:** Both, the file under a size.',
    '',
    '### Assumptions',
    '',
    '- **A:** not a decision, under a heading that names none.',
    '- **B (chosen):** nor this.',
    '',
    '## Steps',
    '',
    '### Step 1: the job',
    '',
    '- **A (chosen):** a list in a step is no decision.',
    '- **B:** nor this.',
].join('\n')

// A decision's heading and its options, as a plan writes them.
function decision(heading: string, ...options: string[]): string {
    return [`### ${heading}`, '', ...options, ''].join('\n')
}

describe('planDecisions', () => {
    it('reads each decision under Decisions: its number, question, options, and the choice', () => {
        expect(planDecisions(PLAN)).toEqual([
            {
                number: 1,
                question: "Where a schedule's hour is kept",
                options: [
                    { letter: 'A', text: "In the owner's timezone: the ticket asks for the owner's hour." },
                    { letter: 'B', text: 'In UTC: simpler to store, but the hour moves when the clocks change.' },
                ],
                chosen: 'A',
            },
            {
                number: 2,
                question: 'What the email carries',
                options: [
                    { letter: 'A', text: 'The file itself: one click, but a large export bounces.' },
                    { letter: 'B', text: 'A link to the file, `/exports/:id`, which works for seven days.' },
                    { letter: 'C', text: 'Both, the file under a size.' },
                ],
                chosen: 'B',
            },
        ])
    })

    it('finds none in a plan written before the shape, or with no Decisions section', () => {
        const prose = '## Decisions\n\nWe chose a link over the file, since large exports bounce.\n\n## Steps\n'
        expect(planDecisions(prose)).toEqual([])
        expect(planDecisions('# Plan\n\n## Steps\n\n### Step 1: a\n')).toEqual([])
        expect(planDecisions('')).toEqual([])
    })

    it('takes the colon outside the bold, a wrapped option, and stops an option at the prose after it', () => {
        const plan = [
            '## Decisions',
            '### Decision 3 — Retries',
            '- **A (chosen)**: Three, as the runner',
            '  does now.',
            '* **B**: None.',
            'Prose after the options is not one.',
            '  Nor is this, though indented.',
        ].join('\n')
        expect(planDecisions(plan)).toEqual([
            {
                number: 3,
                question: 'Retries',
                options: [
                    { letter: 'A', text: 'Three, as the runner does now.' },
                    { letter: 'B', text: 'None.' },
                ],
                chosen: 'A',
            },
        ])
    })

    it('skips a decision that does not hold together, and keeps the rest', () => {
        const plan = [
            '## Decisions',
            '',
            decision('Decision 1: no choice', '- **A:** one', '- **B:** two'),
            decision('Decision 2: two choices', '- **A (chosen):** one', '- **B (chosen):** two'),
            decision('Decision 3: one option', '- **A (chosen):** one'),
            decision('Decision 4: a letter twice', '- **A (chosen):** one', '- **A:** two'),
            decision('Decision 5: an empty option', '- **A (chosen):** one', '- **B:**'),
            decision('Decision 6: kept', '- **A (chosen):** one', '- **B:** two'),
            decision('Decision 6: its number taken', '- **A (chosen):** one', '- **B:** two'),
            decision('Decision seven: no number', '- **A (chosen):** one', '- **B:** two'),
            decision('Decision 8:', '- **A (chosen):** one', '- **B:** two'),
        ].join('\n')
        expect(planDecisions(plan).map((d) => `${d.number} ${d.question}`)).toEqual(['6 kept'])
    })

    it('reads no heading or option inside fenced code', () => {
        const plan = [
            '## Decisions',
            '',
            '```markdown',
            '### Decision 1: in code',
            '- **A (chosen):** one',
            '- **B:** two',
            '```',
            '',
            '~~~',
            '## Steps',
            '~~~',
            '',
            '### Decision 2: outside',
            '',
            '- **A (chosen):** one',
            '- **B:** two',
        ].join('\n')
        expect(planDecisions(plan).map((d) => d.number)).toEqual([2])
    })

    it('reads the plan the same once the editor has written it back as Markdown', () => {
        const editor = new Editor({ extensions: planExtensions(), content: PLAN, contentType: 'markdown' })
        try {
            expect(planDecisions(editor.getMarkdown())).toEqual(planDecisions(PLAN))
        } finally {
            editor.destroy()
        }
    })
})

describe('decisionAnswers', () => {
    const decisions = planDecisions(PLAN)

    it('answers each decision picked other than the planner chose, in plan order, and nothing for the rest', () => {
        expect(decisionAnswers(decisions, new Map())).toEqual([])
        expect(
            decisionAnswers(
                decisions,
                new Map([
                    [2, 'C'],
                    [1, 'A'],
                ]),
            ),
        ).toEqual(['Decision 2 (What the email carries): take C, not B.'])
        expect(
            decisionAnswers(
                decisions,
                new Map([
                    [2, 'A'],
                    [1, 'B'],
                ]),
            ),
        ).toEqual([
            "Decision 1 (Where a schedule's hour is kept): take B, not A.",
            'Decision 2 (What the email carries): take A, not B.',
        ])
    })

    it('answers nothing for a pick the plan no longer offers, or a decision it no longer asks', () => {
        expect(
            decisionAnswers(
                decisions,
                new Map([
                    [1, 'D'],
                    [9, 'B'],
                ]),
            ),
        ).toEqual([])
    })

    it('cuts a long question at a word', () => {
        const question =
            'Whether the export job runs in the existing queue or in a queue of its own with its own workers'
        const long: PlanDecision = {
            number: 4,
            question,
            options: [
                { letter: 'A', text: 'the existing queue' },
                { letter: 'B', text: 'its own' },
            ],
            chosen: 'A',
        }
        const [answer] = decisionAnswers([long], new Map([[4, 'B']]))
        expect(answer).toBe('Decision 4 (Whether the export job runs in the existing queue or in a…): take B, not A.')
        expect(answer?.indexOf('…')).toBeLessThanOrEqual('Decision 4 ('.length + MAX_QUESTION)
    })
})
