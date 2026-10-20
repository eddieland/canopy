import { Link, useNavigate } from '@tanstack/react-router'
import type { ReactNode } from 'react'

import { FilterField } from '@/components/filter-field'
import { PR_QUERY_MAX, prQueryOf } from '@/lib/pull-request-filter'
import type { PullRequestFilter } from '@/lib/pull-request-filter'
import { cn } from '@/lib/utils'

/** The pages a `PullRequestFilterBar` filters, each with `?repo=` and `?q=`. */
type FilteredPage = '/pull-requests' | '/reviews'

/**
 * A PR list's filter, the pull requests page's and the reviews page's: a field for words, kept in `?q=`
 * (`FilterField`), and a chip for each repository the list's rows are in, kept in `?repo=`, while there is more than
 * one. Each keeps the other's key.
 */
export function PullRequestFilterBar({
    to,
    filter,
    repos,
    label,
    placeholder,
}: {
    /** The page it filters. */
    to: FilteredPage
    /** The page's validated search. */
    filter: PullRequestFilter
    /** The repositories to offer a chip for (`reposOf`). */
    repos: string[]
    /** The field's name, for a screen reader. */
    label: string
    /** What the empty field says. */
    placeholder: string
}) {
    const navigate = useNavigate()
    return (
        <search className="flex flex-wrap items-center gap-x-3 gap-y-2 border-b px-3 py-2">
            <FilterField
                q={filter.q}
                queryOf={prQueryOf}
                onFilter={(q) => void navigate({ to, search: { ...filter, q }, replace: true })}
                label={label}
                placeholder={placeholder}
                maxLength={PR_QUERY_MAX}
                className="min-w-48 flex-1 basis-80"
            />
            {repos.length > 1 && (
                <nav aria-label="Filter by repository" className="flex flex-wrap items-center gap-1">
                    <RepoLink to={to} filter={filter} repo={undefined}>
                        every repository
                    </RepoLink>
                    {repos.map((r) => (
                        <RepoLink key={r} to={to} filter={filter} repo={r}>
                            {r}
                        </RepoLink>
                    ))}
                </nav>
            )}
        </search>
    )
}

/** A repository's chip, selected when the validated `?repo=` names it, or `every repository` while none does. */
function RepoLink({
    to,
    filter,
    repo,
    children,
}: {
    to: FilteredPage
    filter: PullRequestFilter
    repo: string | undefined
    children: ReactNode
}) {
    return (
        <Link
            to={to}
            search={{ ...filter, repo }}
            data-selected={filter.repo === repo}
            className={cn(
                'flex h-6 items-center gap-1.5 rounded-sm px-2 font-mono text-xs text-muted-foreground',
                'hover:bg-surface-raised hover:text-foreground',
                'data-[selected=true]:bg-accent/16 data-[selected=true]:text-foreground',
            )}
        >
            {children}
        </Link>
    )
}
