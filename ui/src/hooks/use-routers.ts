import { useQuery } from '@tanstack/react-query'

import { metaQuery } from '@/api/queries'

const NONE: readonly string[] = []

/**
 * The models `runtime.routers` names as routers, each as `provider/model`, beside any whose id ends in `auto`
 * (`isRouter`); none until the server's meta is read.
 */
export function useRouters(): readonly string[] {
    return useQuery(metaQuery).data?.routers ?? NONE
}
