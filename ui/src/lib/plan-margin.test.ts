import { describe, expect, it } from 'vitest'

import { releaseComments, stack } from '@/lib/plan-margin'

describe('stack', () => {
    it('puts each card at its passage when none is in the way of another', () => {
        expect(
            stack(
                [
                    { want: 10, height: 40 },
                    { want: 200, height: 40 },
                ],
                undefined,
                8,
            ),
        ).toEqual([10, 200])
    })

    it('moves a card down to clear the one before it, in the plan’s order', () => {
        expect(
            stack(
                [
                    { want: 10, height: 40 },
                    { want: 20, height: 40 },
                    { want: 30, height: 40 },
                ],
                undefined,
                8,
            ),
        ).toEqual([10, 58, 106])
    })

    it('keeps the open card at its passage, and moves the cards before it up to make room', () => {
        expect(
            stack(
                [
                    { want: 100, height: 40 },
                    { want: 110, height: 40 },
                ],
                1,
                8,
            ),
        ).toEqual([62, 110])
    })

    it('never puts a card above the column’s top, so the open one moves down if it must', () => {
        expect(
            stack(
                [
                    { want: 0, height: 40 },
                    { want: 20, height: 40 },
                ],
                1,
                8,
            ),
        ).toEqual([0, 48])
        expect(stack([{ want: -30, height: 40 }], undefined, 8)).toEqual([0])
    })
})

describe('releaseComments', () => {
    it('puts placed cards back in a plain list', () => {
        const list = document.createElement('div')
        list.dataset['aligned'] = ''
        const card = document.createElement('article')
        card.style.marginTop = '120px'
        list.append(card)
        releaseComments(list)
        expect(card.style.marginTop).toBe('')
        expect('aligned' in list.dataset).toBe(false)
    })
})
