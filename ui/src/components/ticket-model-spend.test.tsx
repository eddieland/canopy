import { cleanup, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import type { AgentModel, SpendModel } from '@/api/types'
import { renderRouted, tipOf } from '@/test-utils'

import { TicketModelSpend } from './ticket-model-spend'

afterEach(cleanup)

const OPUS: SpendModel = {
    kind: 'workers',
    model: 'anthropic/claude-opus-4-1',
    runs: 2,
    replies: 30,
    cost_usd: 2.2,
    workspace_runs: 5,
    workspace_cost_usd: 4.4,
    unread: false,
}
const SONNET: SpendModel = { ...OPUS, model: 'anthropic/claude-sonnet-4-5', runs: 1, cost_usd: 0.6 }
const UNREAD: SpendModel = { ...OPUS, model: null, runs: 3, cost_usd: 1, workspace_runs: 9, unread: true }

function worker(source: AgentModel['source']): AgentModel {
    return {
        agent: 'worker',
        model: source === 'default' ? null : 'anthropic/claude-opus-4-1',
        source,
        variant: null,
        dropped_variant: null,
        last_served: null,
    }
}

describe('TicketModelSpend', () => {
    it("sets each model's worker runs per run beside the workspace's, once two models served them", async () => {
        await renderRouted(
            <TicketModelSpend ticketKey="ABC-1" spend={[OPUS, SONNET, UNREAD]} models={[worker('config')]} />,
        )
        const line = screen.getByTestId('ticket-model-spend')
        expect(line.textContent).toBe(
            'worker spend, 30 days' +
                'claude-opus-4-1: 2 runs, $1.10/run · workspace $0.88/run' +
                'claude-sonnet-4-5: 1 run, $0.60/run · workspace $0.88/run',
        )
        expect(tipOf(screen.getByText(/^claude-opus-4-1/u))).toBe(
            "anthropic/claude-opus-4-1: 2 runs of this ticket's, $1.10 each; 5 runs of the workspace's, these among " +
                'them, $0.88 each',
        )
    })

    it("opens Spend's By model for the ticket over the same 30 days", async () => {
        const { router } = await renderRouted(
            <TicketModelSpend ticketKey="ABC-1" spend={[OPUS, SONNET]} models={[worker('config')]} />,
        )
        screen.getByRole('link', { name: 'worker spend, 30 days' }).click()
        await expect.poll(() => router.state.location.href).toBe('/reports/spend?days=30&ticket=ABC-1')
    })

    it("shows one model when the ticket's override set the workers' model, and none on config's alone", async () => {
        await renderRouted(<TicketModelSpend ticketKey="ABC-1" spend={[OPUS, UNREAD]} models={[worker('ticket')]} />)
        expect(screen.getByTestId('ticket-model-spend').textContent).toContain('claude-opus-4-1: 2 runs')
        cleanup()
        await renderRouted(<TicketModelSpend ticketKey="ABC-1" spend={[OPUS, UNREAD]} models={[worker('config')]} />)
        expect(screen.queryByTestId('ticket-model-spend')).toBeNull()
    })
})
