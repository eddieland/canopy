import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import type { CostTotal } from '@/api/types'
import { Fields } from '@/components/fields'
import { tipOf } from '@/test-utils'

import { CostTotalRow } from './cost-total'

afterEach(cleanup)

const OPUS = { model: 'anthropic/claude-opus-4-1', runs: 3, cost_usd: 4.5 }
const SONNET = { model: 'anthropic/claude-sonnet-4-5', runs: 1, cost_usd: 0.6 }

function renderCost(cost: Partial<CostTotal>) {
    const total = { runs: 4, reviews: 0, priced: 4, cost_usd: 5.6, models: [], ...cost }
    return render(
        <Fields>
            <CostTotalRow cost={total} />
        </Fields>,
    )
}

describe('CostTotalRow', () => {
    it('says the total and what it counted, with no split while one model served it', () => {
        renderCost({ models: [OPUS] })
        expect(screen.getByText('$5.60')).toBeDefined()
        expect(screen.getByText('over 4 runs')).toBeDefined()
        expect(screen.queryByTestId('cost-total-models')).toBeNull()
    })

    it('splits the total by model once more than one served it, the rest as none', () => {
        renderCost({ models: [OPUS, SONNET] })
        const split = screen.getByTestId('cost-total-models')
        expect(split.textContent).toBe('claude-opus-4-1 $4.50claude-sonnet-4-5 $0.60none $0.50')
        expect(tipOf(screen.getByText(/^claude-opus-4-1/u))).toBe('anthropic/claude-opus-4-1, over 3 runs')
    })
})
