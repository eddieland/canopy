import { cleanup, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import type { Tick } from '@/api/types'
import { RUN_TOKENS_TITLE } from '@/lib/transcript'
import { renderRouted, tipOf } from '@/test-utils'

import { TickRow } from './tick-row'

afterEach(() => {
    cleanup()
})

const TICK: Tick = {
    id: 12,
    status: 'ok',
    dry_run: false,
    decisions: 3,
    cost_usd: 0.42,
    new_tokens: 19_320,
    peak_context: 25_200,
    started_at: '2026-10-08T12:00:00Z',
    ended_at: '2026-10-08T12:02:00Z',
    idle: false,
    session_id: 'ses_tick12',
    summary: null,
    woken_by: null,
    canopy_version: null,
    activity: null,
}

function renderRow(tick: Partial<Tick> = {}) {
    return renderRouted(
        <ul>
            <TickRow tick={{ ...TICK, ...tick }} />
        </ul>,
    )
}

describe('TickRow', () => {
    it('heads a tick as `canopy decisions` does: its link, its decisions counted, and its tokens', async () => {
        await renderRow()
        expect(screen.getByRole('link', { name: 'tick:12' }).getAttribute('href')).toBe('/workspace/ticks/12')
        expect(screen.getByText('3 decisions')).toBeDefined()
        expect(screen.getByText('19.3k tokens').title).toBe(RUN_TOKENS_TITLE)
        expect(screen.getByText('25.2k peak').title).toBe(RUN_TOKENS_TITLE)
        expect(screen.queryByText('dry run')).toBeNull()
    })

    it("reads its status with the CLI's spelling in its tip, counts one decision as one, marks a dry run", async () => {
        await renderRow({ status: 'overseer_failed', decisions: 1, dry_run: true })
        expect(tipOf(screen.getByText('overseer failed'))).toBe('overseer_failed')
        expect(screen.getByText('1 decision')).toBeDefined()
        expect(screen.getByText('dry run')).toBeDefined()
    })

    it('shows a dash, and says none was reported, for a cost or tokens the overseer did not report', async () => {
        await renderRow({ cost_usd: null, new_tokens: null, peak_context: null })
        const dashes = screen.getAllByText('–')
        expect(dashes).toHaveLength(3)
        for (const dash of dashes) {
            expect(dash.title).toBe('none reported')
        }
    })

    it("lays its summary out under it as rich text, the overseer's markup set and its URLs linked", async () => {
        await renderRow({ summary: 'Dispatched **ABC-1**; see https://ci.example.test/7' })
        expect(screen.getByRole('strong').textContent).toBe('ABC-1')
        expect(screen.getByRole('link', { name: 'https://ci.example.test/7' })).toBeDefined()
    })
})
