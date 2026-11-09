import { cleanup, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import type { PlanCheck } from '@/api/types'
import { renderRouted } from '@/test-utils'

import { PLAN_FOLLOWED, PlanCheckPanel } from './run-plan-check'

afterEach(() => {
    cleanup()
})

function check(fields: Partial<PlanCheck> = {}): PlanCheck {
    return { plan_id: 3, unnamed: [], untouched: [], unchecked: null, ...fields }
}

describe('PlanCheckPanel', () => {
    it('lists the files no step names and the steps none of whose files were touched, as text', async () => {
        await renderRouted(
            <PlanCheckPanel
                ticketKey="ABC-102"
                check={check({
                    unnamed: [{ repo: 'web', path: 'src/<img src=x onerror=alert(1)>.ts' }],
                    untouched: [{ number: 2, title: 'Document the export' }],
                })}
            />,
        )
        const files = screen.getByRole('region', { name: 'Touched, named by no step' })
        expect(within(files).getByText('web')).toBeTruthy()
        // The branch's text stays its characters.
        expect(within(files).getByText('src/<img src=x onerror=alert(1)>.ts')).toBeTruthy()
        expect(document.querySelector('img')).toBeNull()
        const steps = screen.getByRole('region', { name: 'Steps none of whose files it touched' })
        expect(within(steps).getByText('Step 2: Document the export')).toBeTruthy()
        expect(screen.getByRole('link', { name: 'plan 3' }).getAttribute('href')).toBe('/tickets/ABC-102/plan')
    })

    it('says when nothing stands out, and why nothing was held', async () => {
        const { unmount } = await renderRouted(<PlanCheckPanel ticketKey="ABC-102" check={check()} />)
        expect(screen.getByText(PLAN_FOLLOWED)).toBeTruthy()
        expect(screen.queryByRole('region', { name: 'Touched, named by no step' })).toBeNull()
        unmount()
        await renderRouted(
            <PlanCheckPanel ticketKey="ABC-102" check={check({ unchecked: 'plan 3’s file is missing' })} />,
        )
        expect(screen.getByText('Not held to the plan: plan 3’s file is missing')).toBeTruthy()
    })

    it('shows nothing for a run that followed no plan', async () => {
        await renderRouted(<PlanCheckPanel ticketKey="ABC-102" check={null} />)
        expect(screen.queryByTestId('plan-check')).toBeNull()
    })
})
