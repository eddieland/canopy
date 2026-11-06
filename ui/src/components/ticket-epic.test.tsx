import { cleanup, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import type { FollowedEpicPlan, TicketMembership } from '@/api/types'
import { Fields } from '@/components/fields'
import { renderRouted } from '@/test-utils'

import { FollowedEpicPlanLine, MembershipField } from './ticket-epic'

afterEach(() => {
    cleanup()
})

const MEMBER: TicketMembership = { epic_id: 1, entries: ['B2', 'B3'], dropped: [], added_at: '2026-10-08T07:10:00Z' }

const SHA = '3f2a9c1e4b5d6a7b8c9d0e1f2a3b4c5d6e7f8a9b0c1d2e3f4a5b6c7d8e9f0a1b'

const FOLLOWED: FollowedEpicPlan = {
    epic_id: 1,
    plan_id: 1,
    sha256: SHA,
    approved_at: '2026-10-08T02:00:00Z',
    newer_approved_at: null,
}

/** The ticket's Work panel's field for `membership`, in a field list as the panel has it. */
async function field(membership: TicketMembership | null) {
    await renderRouted(
        <Fields data-testid="fields">
            <MembershipField membership={membership} />
        </Fields>,
    )
    return screen.getByTestId('fields')
}

describe('MembershipField', () => {
    it('names the epic, opening its page, and the entries the member fulfils', async () => {
        const shown = await field(MEMBER)
        expect(shown.textContent).toBe('member ofepic:1 · B2, B3')
        expect(screen.getByRole('link', { name: 'epic:1' }).getAttribute('href')).toBe('/epics/1')
    })

    it('says a member of no entry is one', async () => {
        const shown = await field({ ...MEMBER, entries: [] })
        expect(shown.textContent).toBe('member ofepic:1 · of no entry')
        expect(screen.getByRole('link', { name: 'epic:1' })).toBeTruthy()
    })

    it('sets apart the entries a later approved plan dropped', async () => {
        const shown = await field({ ...MEMBER, entries: ['B3'], dropped: ['B2'] })
        expect(shown.textContent).toBe('member ofepic:1 · B3 · B2 dropped')
    })

    it('shows nothing for a ticket of no epic', async () => {
        const shown = await field(null)
        expect(shown.textContent).toBe('')
    })
})

describe('FollowedEpicPlanLine', () => {
    it('names the epic plan the plan follows, by its hash, and when it was approved', async () => {
        await renderRouted(<FollowedEpicPlanLine followed={FOLLOWED} />)
        const line = screen.getByTestId('plan-epic')
        expect(line.textContent).toMatch(/^follows/u)
        expect(line.textContent).toContain('epic:1’s plan')
        expect(line.textContent).toContain('3f2a9c1e4b5d')
        expect(line.textContent).not.toContain(SHA)
        expect(line.textContent).toMatch(/, approved .+ ago\.$/u)
        expect(screen.getByRole('link', { name: 'epic:1' }).getAttribute('href')).toBe('/epics/1')
        expect(screen.queryByTestId('plan-epic-newer')).toBeNull()
    })

    it('says, as a fact, that a newer epic plan was approved since', async () => {
        await renderRouted(
            <FollowedEpicPlanLine followed={{ ...FOLLOWED, newer_approved_at: '2026-10-08T09:00:00Z' }} />,
        )
        expect(screen.getByTestId('plan-epic-newer').textContent).toMatch(/^ A newer epic plan was approved .+ ago\.$/u)
    })

    it('shows nothing for a plan of a ticket of no epic', async () => {
        await renderRouted(<FollowedEpicPlanLine followed={null} />)
        expect(screen.queryByTestId('plan-epic')).toBeNull()
    })
})
