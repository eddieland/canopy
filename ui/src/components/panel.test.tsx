import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import {
    createMemoryHistory,
    createRootRoute,
    createRoute,
    createRouter,
    Link,
    RouterProvider,
} from '@tanstack/react-router'
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { ApiError } from '@/api/client'
import { mockAttention } from '@/api/mocks'
import { keys } from '@/api/queries'
import type { AttentionItem } from '@/api/types'
import { renderRouted } from '@/test-utils'

import { PageHeader, PanelLoading, ThreadScroll } from './panel'

afterEach(() => {
    cleanup()
})

// A client holding the attention items as the stream wrote them, which reads nothing itself.
function client(attention: AttentionItem[] | undefined): QueryClient {
    const queries = new QueryClient()
    queries.setQueryDefaults(keys.attention, { enabled: false })
    if (attention !== undefined) {
        queries.setQueryData(keys.attention, attention)
    }
    return queries
}

function trail(): HTMLElement {
    return screen.getByRole('navigation', { name: 'Breadcrumb' })
}

describe('PageHeader', () => {
    it('names the tab for the page and its subject, after how many attention items block work', async () => {
        const finding = { ...mockAttention[0], id: 'f1', finding: true } as AttentionItem
        await renderRouted(<PageHeader title="run:39" subject="Debounce search input" />, {
            at: '/runs/39',
            client: client([...mockAttention, finding]),
        })
        expect(document.title).toBe('(1) run:39 Debounce search input · canopy')
        expect(screen.getByRole('heading', { level: 1 }).textContent).toBe('run:39 Debounce search input')
    })

    it('names the tab with `tab` for a title not plain text, with no count before the items arrive', async () => {
        await renderRouted(<PageHeader title={<span>Memory</span>} tab="Memory" root="Memory" />, {
            at: '/memory',
            client: client(undefined),
        })
        expect(document.title).toBe('Memory · canopy')
    })

    it('is only the section’s name on the section’s own list', async () => {
        await renderRouted(<PageHeader title="Runs" />, { at: '/runs', client: client([]) })
        expect(trail().textContent).toBe('Runs')
        expect(within(trail()).queryByRole('link')).toBeNull()
    })

    it('links up to the section, then each page between it and this one', async () => {
        const parents = (
            <Link to="/chores/$name" params={{ name: 'deps' }} activeOptions={{ exact: true }}>
                deps
            </Link>
        )
        await renderRouted(<PageHeader title="chore-run:deps/2" parents={parents} />, {
            at: '/chores/deps/runs/2',
            client: client([]),
        })
        const links = within(trail()).getAllByRole('link')
        expect(links.map((link) => [link.textContent, link.getAttribute('href')])).toEqual([
            ['Chores', '/chores'],
            ['deps', '/chores/deps'],
        ])
    })

    it('starts the trail with its root on a page in no section', async () => {
        await renderRouted(<PageHeader title="Search" root="Search" />, { at: '/search', client: client([]) })
        expect(trail().textContent).toBe('Search')
    })

    it('opens the guide’s page about the page shown from a book, and has none in the guide itself', async () => {
        const runs = createRootRoute()
        const run = createRoute({
            getParentRoute: () => runs,
            path: '/runs/$id',
            component: () => <PageHeader title="run:39" />,
        })
        const guide = createRoute({
            getParentRoute: () => runs,
            path: '/guide/$page',
            component: () => <PageHeader title="Runs and worktrees" root="The loop" />,
        })
        const router = createRouter({
            routeTree: runs.addChildren([run, guide]),
            history: createMemoryHistory({ initialEntries: ['/runs/39'] }),
        })
        await router.load()
        render(
            <QueryClientProvider client={client([])}>
                <RouterProvider router={router} />
            </QueryClientProvider>,
        )
        const book = await screen.findByRole('link', { name: 'The guide: Runs and worktrees' })
        expect(book.getAttribute('href')).toBe('/guide/runs#a-runs-page')
        fireEvent.click(book)
        await screen.findByRole('heading', { level: 1, name: 'Runs and worktrees' })
        expect(screen.queryByRole('link', { name: /^The guide/u })).toBeNull()
    })

    it('says what every page of its kind shows on the title’s hover, and a description only if any', async () => {
        const { unmount } = await renderRouted(
            <PageHeader title="run:39" help="A run’s page: what it did, and its transcript." />,
            { at: '/runs/39', client: client([]) },
        )
        expect(screen.getByRole('heading', { level: 1 }).title).toBe('A run’s page: what it did, and its transcript.')
        expect(screen.queryByRole('paragraph')).toBeNull()
        unmount()

        await renderRouted(<PageHeader title="run:39">Waiting on your answer.</PageHeader>, {
            at: '/runs/39',
            client: client([]),
        })
        expect(screen.getByRole('paragraph').textContent).toBe('Waiting on your answer.')
    })
})

// Stands in for ResizeObserver: a test says when what it watches changed size.
class FakeResizeObserver {
    static last: FakeResizeObserver | undefined
    readonly #callback: () => void

    constructor(callback: () => void) {
        this.#callback = callback
        FakeResizeObserver.last = this
    }

    observe(): void {}

    disconnect(): void {}

    resized(): void {
        this.#callback()
    }
}

// The thread's region, its content `height` pixels tall in a box 200 high.
function measure(region: HTMLElement, height: number) {
    Object.defineProperty(region, 'scrollHeight', { value: height, configurable: true })
    Object.defineProperty(region, 'clientHeight', { value: 200, configurable: true })
}

function grow(region: HTMLElement, height: number) {
    measure(region, height)
    FakeResizeObserver.last?.resized()
}

function scrollTo(region: HTMLElement, top: number) {
    region.scrollTop = top
    fireEvent.scroll(region)
}

describe('PanelLoading', () => {
    it('shimmers while the read is pending, and says nothing failed', () => {
        render(<PanelLoading query={{ error: null, isFetching: true, refetch: vi.fn<() => Promise<unknown>>() }} />)
        expect(screen.getByTestId('panel-skeleton')).toBeTruthy()
        expect(screen.queryByRole('alert')).toBeNull()
    })

    it('says why a failed read failed, in place of the skeleton, and reads again when asked', () => {
        const refetch = vi.fn<() => Promise<unknown>>(async () => {})
        render(
            <PanelLoading
                query={{ error: new ApiError(500, 'database is locked'), isFetching: false, refetch }}
                className="min-h-72"
            />,
        )
        expect(screen.queryByTestId('panel-skeleton')).toBeNull()
        expect(screen.getByRole('alert').textContent).toBe(
            'could not read it: the server answered 500: database is locked',
        )
        fireEvent.click(screen.getByRole('button', { name: 'Read again' }))
        expect(refetch).toHaveBeenCalledOnce()
    })

    it('holds Read again while the read it asked for is in flight', () => {
        render(
            <PanelLoading
                query={{
                    error: new TypeError('Failed to fetch'),
                    isFetching: true,
                    refetch: vi.fn<() => Promise<unknown>>(),
                }}
            />,
        )
        expect(screen.getByRole('button', { name: 'Reading' }).hasAttribute('disabled')).toBe(true)
    })
})

describe('ThreadScroll', () => {
    it('keeps to the newest end as the thread grows, but not while the operator reads further up', () => {
        vi.stubGlobal('ResizeObserver', FakeResizeObserver)
        render(
            <ThreadScroll label="Conversation" end="bottom">
                <p>message 1</p>
            </ThreadScroll>,
        )
        const region = screen.getByRole('region', { name: 'Conversation' })
        grow(region, 1000)
        expect(region.scrollTop).toBe(1000)

        // Scrolled up to read: a new message leaves the operator where they are.
        scrollTo(region, 300)
        grow(region, 1400)
        expect(region.scrollTop).toBe(300)

        // Back within a bubble's gap of the end, it keeps to it again.
        scrollTo(region, 1400 - 200 - 10)
        grow(region, 1800)
        expect(region.scrollTop).toBe(1800)
    })

    it('keeps to the top when the thread runs newest first', () => {
        vi.stubGlobal('ResizeObserver', FakeResizeObserver)
        render(
            <ThreadScroll label="Conversation" end="top">
                <p>message 1</p>
            </ThreadScroll>,
        )
        const region = screen.getByRole('region', { name: 'Conversation' })
        measure(region, 1000)
        scrollTo(region, 8)
        grow(region, 1400)
        expect(region.scrollTop).toBe(0)
        scrollTo(region, 300)
        grow(region, 1800)
        expect(region.scrollTop).toBe(300)
    })
})
