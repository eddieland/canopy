import { cleanup, fireEvent, render, screen, within } from '@testing-library/react'
import { useState } from 'react'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { RepoFilter, RepoSelect } from './repo-picker'

afterEach(cleanup)

// A workspace past what a row of chips holds.
const MANY = Array.from({ length: 40 }, (_, i) => `service-${String(i).padStart(2, '0')}`)
const NONE: string[] = []

/** A `RepoFilter` that keeps what is chosen, as a page's search does. */
function Filter({ repos, start = NONE }: { repos: string[]; start?: string[] }) {
    const [chosen, setChosen] = useState(start)
    return <RepoFilter repos={repos} chosen={chosen} onChoose={setChosen} />
}

function open(name: RegExp | string) {
    fireEvent.click(screen.getByRole('button', { name }))
    return screen.getByRole('listbox')
}

function names(list: HTMLElement): string[] {
    return within(list)
        .getAllByRole('option')
        .map((o) => o.textContent)
}

function checked(list: HTMLElement): string[] {
    return within(list)
        .getAllByRole('option')
        .filter((o) => o.getAttribute('aria-checked') === 'true')
        .map((o) => o.textContent)
}

describe('RepoFilter', () => {
    it('says it filters nothing, and lists every repository under the item that clears them', () => {
        render(<Filter repos={['api', 'web', 'worker']} />)
        const list = open('Filter by repository: every repository')
        expect(names(list)).toEqual(['every repository', 'api', 'web', 'worker'])
        expect(checked(list)).toEqual(['every repository'])
    })

    it('chooses several, keeping the list open, and says what it chose', () => {
        render(<Filter repos={['api', 'web', 'worker']} />)
        const list = open(/^Filter by repository/u)
        fireEvent.click(within(list).getByRole('option', { name: 'web' }))
        fireEvent.click(within(list).getByRole('option', { name: 'api' }))
        expect(checked(screen.getByRole('listbox'))).toEqual(['api', 'web'])
        expect(screen.getByRole('button', { name: 'Filter by repository: api, web' })).toBeDefined()

        fireEvent.click(within(list).getByRole('option', { name: 'worker' }))
        expect(screen.getByRole('button', { name: 'Filter by repository: 3 repositories' })).toBeDefined()

        // Picked again, one is taken away; every repository clears the rest.
        fireEvent.click(within(list).getByRole('option', { name: 'web' }))
        expect(checked(screen.getByRole('listbox'))).toEqual(['api', 'worker'])
        fireEvent.click(within(list).getByRole('option', { name: 'every repository' }))
        expect(checked(screen.getByRole('listbox'))).toEqual(['every repository'])
    })

    it('lists what was chosen first as it opens, and keeps the order while it is open', () => {
        render(<Filter repos={MANY} start={['service-31']} />)
        const list = open('Filter by repository: service-31')
        expect(names(list).slice(0, 3)).toEqual(['every repository', 'service-31', 'service-00'])

        fireEvent.click(within(list).getByRole('option', { name: 'service-05' }))
        expect(names(screen.getByRole('listbox')).slice(0, 3)).toEqual(['every repository', 'service-31', 'service-00'])
    })

    it('narrows a long list to the names that hold what is typed', () => {
        render(<Filter repos={MANY} />)
        const list = open(/^Filter by repository/u)
        fireEvent.change(screen.getByRole('combobox', { name: 'Find a repository' }), { target: { value: '3' } })
        expect(names(list)).toEqual([
            'service-03',
            'service-13',
            'service-23',
            'service-30',
            'service-31',
            'service-32',
            'service-33',
            'service-34',
            'service-35',
            'service-36',
            'service-37',
            'service-38',
            'service-39',
        ])

        fireEvent.change(screen.getByRole('combobox', { name: 'Find a repository' }), { target: { value: 'nope' } })
        expect(within(list).getByText('no repository has that name')).toBeDefined()
    })
})

describe('RepoSelect', () => {
    it('offers the choices in order, picks one, and closes', () => {
        const onValue = vi.fn<(repo: string | null) => void>()
        render(<RepoSelect choices={[null, 'web', 'api']} value="web" onValue={onValue} label="Served to runs in" />)
        const list = open('Served to runs in: web')
        expect(names(list)).toEqual(['every repository', 'web', 'api'])
        expect(checked(list)).toEqual(['web'])

        fireEvent.click(within(list).getByRole('option', { name: 'every repository' }))
        expect(onValue).toHaveBeenCalledWith(null)
        expect(screen.queryByRole('listbox')).toBeNull()
    })

    it('says what none chosen means, when every repository is not among the choices', () => {
        const onValue = vi.fn<(repo: string | null) => void>()
        render(
            <RepoSelect
                choices={['web', 'api']}
                value={null}
                none="pick a repository"
                onValue={onValue}
                label="Give its own count"
            />,
        )
        const list = open('Give its own count: pick a repository')
        expect(names(list)).toEqual(['web', 'api'])
        expect(checked(list)).toEqual([])

        fireEvent.click(within(list).getByRole('option', { name: 'api' }))
        expect(onValue).toHaveBeenCalledWith('api')
    })
})
