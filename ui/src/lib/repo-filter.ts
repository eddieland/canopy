/**
 * A filter by repository, as the memory, pull requests, and reviews pages keep it in `?repo=` (DESIGN.md, the
 * repository picker): the names chosen, sorted and joined by commas, `?repo=api,web`. A comma is in no repository's
 * name, and one name alone is what the pages kept before they took several, so a link to one still works.
 */

/** A repository's name, as the workspace map holds it: lowercase letters, digits, and hyphens. */
const REPO_NAME = /^[a-z0-9-]{1,64}$/u

/**
 * A `?repo=` as the pages filter by it: each name in it that a repository could have, once, sorted and joined by
 * commas; undefined when none is, which filters nothing.
 */
export function repoListOf(raw: unknown): string | undefined {
    if (typeof raw !== 'string') {
        return undefined
    }
    return repoListFrom(raw.split(',').filter((name) => REPO_NAME.test(name)))
}

/** The `?repo=` that chooses `repos`: their names, once, sorted and joined by commas, or undefined for none. */
export function repoListFrom(repos: Iterable<string>): string | undefined {
    const names = [...new Set(repos)].toSorted()
    return names.length === 0 ? undefined : names.join(',')
}

/** The names a validated `?repo=` chooses, none when it is undefined. */
export function reposIn(list: string | undefined): string[] {
    return list === undefined ? [] : list.split(',')
}

/** Whether a row in `repo` is shown under `list`: every row while none is chosen, else a row in one of them. */
export function inRepos(repo: string | null, list: string | undefined): boolean {
    return list === undefined || (repo !== null && reposIn(list).includes(repo))
}

/** The repositories a filter chooses, as an empty list says them: `api`, `api or web`, `api, web, or worker`. */
export function reposWords(list: string): string {
    const names = reposIn(list)
    const last = names.pop() ?? ''
    if (names.length === 0) {
        return last
    }
    return names.length === 1 ? `${names[0] ?? ''} or ${last}` : `${names.join(', ')}, or ${last}`
}

/**
 * What a picker's button says of the repositories chosen: `every repository` for none, a name, two names, or how many
 * past two, which would not fit beside the filter field.
 */
export function reposSummary(chosen: readonly string[]): string {
    if (chosen.length === 0) {
        return 'every repository'
    }
    return chosen.length <= 2 ? chosen.join(', ') : `${chosen.length} repositories`
}
