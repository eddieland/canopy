import { useQuery } from '@tanstack/react-query'
import type { UseQueryResult } from '@tanstack/react-query'

import { attentionQuery } from '@/api/queries'
import type { AttentionItem } from '@/api/types'
import { useFindingsHidden, withoutFindings } from '@/lib/attention-findings'

/**
 * The attention list as the operator reads it: without chores' findings while Settings hides them
 * (`src/lib/attention-findings.ts`). The page, its counter, and the nav's badge read it; what reads the list for
 * anything else, such as a ticket's question, reads `attentionQuery` whole.
 */
export function useAttention(): UseQueryResult<AttentionItem[]> {
    // A select at module level, so the list it makes is kept until the data or the setting changes.
    return useQuery({ ...attentionQuery, select: useFindingsHidden() ? withoutFindings : undefined })
}
