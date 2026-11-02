import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createMemoryHistory, createRootRoute, createRouter, RouterProvider } from '@tanstack/react-router'
import type { AnyRouter } from '@tanstack/react-router'
import { cleanup, render, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'

import { keys } from '@/api/queries'
import type { ChecklistList } from '@/api/types'

import { Route } from './workspace.checklists'

afterEach(() => {
    cleanup()
})

// Why canopy cannot use `web`'s list, as the server says it.
const WEB_ERROR = "the checklist of web at web.md: line 1: each item opens with a '## <id>' heading"

// Three repositories: one with a list of two items, one with none, and one whose file canopy cannot use.
const LISTS: ChecklistList = {
    directory: '/home/op/.config/canopy/checklists',
    repos: [
        {
            repo: 'api',
            file: '/home/op/.config/canopy/checklists/api.md',
            items: [
                {
                    id: 'general-types',
                    paths: [],
                    severity: 'minor',
                    rule: 'A parameter takes the most general type its body needs.',
                },
                {
                    id: 'migration-companion',
                    paths: ['migrations/', 'tests/**/migrations/'],
                    severity: 'blocking',
                    rule: 'A new migration has its companion.',
                },
            ],
            error: null,
        },
        { repo: 'mobile', file: '/home/op/.config/canopy/checklists/mobile.md', items: [], error: null },
        {
            repo: 'web',
            file: '/home/op/.config/canopy/checklists/web.md',
            items: [],
            error: WEB_ERROR,
        },
    ],
}

/** The checklists page, its lists already read as `lists`. */
async function renderPage(lists: ChecklistList = LISTS) {
    // Nothing reads the server: the lists are the ones set here, and every other query stays off.
    const client = new QueryClient({ defaultOptions: { queries: { enabled: false } } })
    client.setQueryData(keys.checklists, lists)
    const root = createRootRoute()
    const page = Route.update({
        id: '/workspace/checklists',
        path: '/workspace/checklists',
        getParentRoute: () => root,
    } as never)
    const router = createRouter({
        routeTree: root.addChildren([page]),
        history: createMemoryHistory({ initialEntries: ['/workspace/checklists'] }),
    })
    await router.load()
    render(
        <QueryClientProvider client={client}>
            <RouterProvider router={router as AnyRouter} />
        </QueryClientProvider>,
    )
}

describe('the checklists page', () => {
    it('says how many repositories keep a list, and where the lists are read from', async () => {
        await renderPage()
        expect(await screen.findByText('1 of 3 repositories keep a list · 2 items · 1 cannot be read')).toBeTruthy()
        expect(screen.getByTestId('checklists-directory').textContent).toBe(LISTS.directory)
    })

    it('lists each item in order: its severity, its paths or every path, its rule, and its answers', async () => {
        await renderPage()
        const panel = await screen.findByTestId('checklist-api')
        const items = within(panel).getAllByRole('listitem')
        expect(items.map((li) => within(li).getByRole('heading').textContent)).toEqual([
            'general-types',
            'migration-companion',
        ])
        const first = within(screen.getByTestId('checklist-item-general-types'))
        expect(first.getByText('every path')).toBeTruthy()
        expect(first.getByText('minor')).toBeTruthy()
        expect(first.getByText('A parameter takes the most general type its body needs.')).toBeTruthy()
        const second = within(screen.getByTestId('checklist-item-migration-companion'))
        expect(second.getByText('blocking')).toBeTruthy()
        expect(second.getByText('tests/**/migrations/')).toBeTruthy()
        const answers = second.getByRole('link', { name: 'Answers' })
        expect(answers.getAttribute('href')).toBe('/reports/checklist?repo=api&item=api%3Amigration-companion')
    })

    it('says a repository without a file has no list, and why one canopy cannot use refuses its runs', async () => {
        await renderPage()
        expect(within(await screen.findByTestId('checklist-mobile')).getByText(/no list/u)).toBeTruthy()
        const alert = within(screen.getByTestId('checklist-web')).getByRole('alert')
        expect(alert.textContent).toBe(`runs refused (bad_prompt): ${WEB_ERROR}`)
    })

    it('shows no panels when no directory is set, and says so', async () => {
        await renderPage({ directory: null, repos: [{ repo: 'api', file: null, items: [], error: null }] })
        expect(await screen.findByText('no repository is asked: paths.checklists is not set')).toBeTruthy()
        expect(screen.queryByTestId('checklist-api')).toBeNull()
    })
})
