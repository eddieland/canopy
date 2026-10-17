import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { TicketLinks } from './ticket-links'

afterEach(() => {
    cleanup()
})

const TRACKER = 'https://acme.atlassian.net/browse/ABC-1'
const WEB_PR = 'https://github.com/acme/web/pull/88'
const API_PR = 'https://github.com/acme/api/pull/12'

// The links out, as their names read, in order.
function names(): string[] {
    return within(screen.getByRole('navigation', { name: 'Links out' }))
        .getAllByRole('link')
        .map((link) => link.textContent)
}

describe('TicketLinks', () => {
    it('renders nothing when the ticket has no link out, a unit without a PR included', () => {
        const { container } = render(<TicketLinks units={[{ repo: 'web', pr_url: null }]} />)
        expect(container.childElementCount).toBe(0)
    })

    it('links the tracker, then each kind with one link as its own button, each opening a new tab', () => {
        render(
            <TicketLinks
                tracker={TRACKER}
                units={[
                    { repo: 'web', pr_url: WEB_PR },
                    { repo: 'api', pr_url: null },
                ]}
                branches={[{ repo: 'web', href: 'https://github.com/acme/web/tree/agent/ABC-1' }]}
            />,
        )
        expect(names()).toEqual([
            'acme.atlassian.net/browse/ABC-1',
            'acme/web#88',
            'github.com/acme/web/tree/agent/ABC-1',
        ])
        expect(screen.getByRole('link', { name: 'acme/web#88' }).title).toBe('The PR in web')
        for (const link of screen.getAllByRole<HTMLAnchorElement>('link')) {
            expect(link.target).toBe('_blank')
            expect(link.rel).toBe('noreferrer noopener')
        }
    })

    it('gathers a kind with a link in each repository into one button that opens them as a menu', () => {
        render(
            <TicketLinks
                units={[
                    { repo: 'web', pr_url: WEB_PR },
                    { repo: 'api', pr_url: API_PR },
                ]}
                branches={[
                    { repo: 'web', href: 'https://github.com/acme/web/tree/agent/ABC-1' },
                    { repo: 'api', href: 'https://github.com/acme/api/tree/agent/ABC-1' },
                ]}
            />,
        )
        expect(screen.queryByRole('link')).toBeNull()
        expect(screen.getByRole('button', { name: '2 branches' })).toBeDefined()

        fireEvent.pointerDown(screen.getByRole('button', { name: '2 PRs' }), { button: 0, ctrlKey: false })
        const menu = screen.getByRole('menu')
        const items = within(menu).getAllByRole('menuitem')
        expect(items.map((item) => item.textContent)).toEqual(['acme/web#88', 'acme/api#12'])
        expect(items.map((item) => item.getAttribute('href'))).toEqual([WEB_PR, API_PR])
        expect(items.map((item) => item.title)).toEqual(['The PR in web', 'The PR in api'])
    })

    it('names a branch in its menu by its repository, the branch being the same in each, its address on hover', () => {
        render(
            <TicketLinks
                branches={[
                    { repo: 'web', href: 'https://github.com/acme/web/tree/agent/ABC-1' },
                    { repo: 'api', href: 'https://github.com/acme/api/tree/agent/ABC-1' },
                ]}
            />,
        )
        fireEvent.pointerDown(screen.getByRole('button', { name: '2 branches' }), { button: 0, ctrlKey: false })
        const branches = within(screen.getByRole('menu')).getAllByRole('menuitem')
        expect(branches.map((item) => item.textContent)).toEqual(['web', 'api'])
        expect(branches[1]?.title).toBe('The branch in api: github.com/acme/api/tree/agent/ABC-1')
    })
})
