import { cleanup, screen } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import type { FeedbackPlanWritten, WaitingFeedbackPlan } from '@/api/types'
import { renderRouted } from '@/test-utils'

import { FeedbackPlanCard, WroteFeedbackPlan } from './feedback-plan-card'

const PR = 'https://github.com/acme/web/pull/88'
const PLAN: WaitingFeedbackPlan = { id: 7, pr_urls: [PR], items: 3, stale: false }
const PR_PAGE = `/pull-requests/pr?url=${encodeURIComponent(PR)}#feedback-plan`

afterEach(cleanup)

describe('FeedbackPlanCard', () => {
    it('names the plan waiting on you, its items, and links to the PR page at the plan', async () => {
        await renderRouted(<FeedbackPlanCard led={PLAN} plan={PLAN} />, { at: '/tickets/ABC-099' })
        const card = screen.getByTestId('feedback-plan-card')
        expect(card.textContent).toContain('feedback-plan:7')
        expect(card.textContent).toContain('waiting on you')
        expect(card.textContent).toContain('Feedback plan 7 for acme/web#88 waits on you: 3 items.')
        const link = screen.getByRole('link', { name: 'Approve it on acme/web#88' })
        expect(link.getAttribute('href')).toBe(PR_PAGE)
    })

    it('says when its PR has moved on since the plan was written', async () => {
        await renderRouted(<FeedbackPlanCard led={PLAN} plan={{ ...PLAN, stale: true, items: 1 }} />)
        expect(screen.getByTestId('feedback-plan-card').textContent).toContain(
            'waits on you: 1 item, and its PR has moved on since it was written.',
        )
    })

    it('stays once the plan waits no more, saying so, and still links to the PR', async () => {
        await renderRouted(<FeedbackPlanCard led={PLAN} plan={null} />)
        const card = screen.getByTestId('feedback-plan-card')
        expect(card.textContent).toContain('answered')
        expect(card.textContent).toContain('Feedback plan 7 for acme/web#88 waits on you no more.')
        expect(screen.getByRole('link', { name: 'See it on acme/web#88' }).getAttribute('href')).toBe(PR_PAGE)
    })
})

describe('WroteFeedbackPlan', () => {
    const WROTE: FeedbackPlanWritten = { id: 7, pr_urls: [PR], status: 'waiting' }

    it('links the plan to the PR page at the plan, names the PR, and says where the plan stands', async () => {
        await renderRouted(<WroteFeedbackPlan plan={WROTE} />, { at: '/runs/46' })
        const field = screen.getByTestId('run-feedback-plan')
        expect(screen.getByRole('link', { name: 'feedback-plan:7' }).getAttribute('href')).toBe(PR_PAGE)
        expect(screen.getByRole('link', { name: 'acme/web#88' })).toBeTruthy()
        expect(field.textContent).toContain('waiting on you')
    })

    it('says the plan was approved, spent, or superseded', async () => {
        await renderRouted(<WroteFeedbackPlan plan={{ ...WROTE, status: 'spent' }} />)
        expect(screen.getByTestId('run-feedback-plan').textContent).toContain('spent')
    })

    it('names a plan with no PR without a link', async () => {
        await renderRouted(<WroteFeedbackPlan plan={{ ...WROTE, pr_urls: [], status: 'superseded' }} />)
        expect(screen.queryByRole('link')).toBeNull()
        expect(screen.getByTestId('run-feedback-plan').textContent).toContain('feedback-plan:7')
    })
})
