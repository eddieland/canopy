import { useQuery } from '@tanstack/react-query'

import { metaQuery } from '@/api/queries'
import { branchUrl } from '@/lib/branch-url'

/**
 * A function giving a branch's page on a repository's host, from that repository's `branch_url`; it gives undefined
 * when the repository has none, or the server's meta is not read yet.
 */
export function useBranchUrls(): (repo: string | null, branch: string) => string | undefined {
    const meta = useQuery(metaQuery)
    const templates = meta.data?.branch_urls
    return (repo, branch) => (repo === null ? undefined : branchUrl(templates?.[repo], branch))
}
