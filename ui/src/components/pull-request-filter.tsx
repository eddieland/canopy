import { useNavigate } from '@tanstack/react-router'

import { FilterField } from '@/components/filter-field'
import { RepoFilter } from '@/components/repo-picker'
import { PR_QUERY_MAX, prQueryOf } from '@/lib/pull-request-filter'
import type { PullRequestFilter } from '@/lib/pull-request-filter'
import { repoListFrom, reposIn } from '@/lib/repo-filter'

/** The pages a `PullRequestFilterBar` filters, each with `?repo=` and `?q=`. */
type FilteredPage = '/pull-requests' | '/pull-requests/reviews'

/**
 * A PR list's filter, the pull requests page's and the reviews page's: a field for words, kept in `?q=`
 * (`FilterField`), and a picker of the repositories the list's rows are in, kept in `?repo=`, while there is more than
 * one (`RepoFilter`). Each keeps the other's key, and replaces the history entry, so Back leaves the page.
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
    /** The repositories to offer (`reposOf`). */
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
                <RepoFilter
                    repos={repos}
                    chosen={reposIn(filter.repo)}
                    onChoose={(chosen) =>
                        void navigate({ to, search: { ...filter, repo: repoListFrom(chosen) }, replace: true })
                    }
                />
            )}
        </search>
    )
}
