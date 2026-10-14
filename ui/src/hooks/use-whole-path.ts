import { useQuery } from '@tanstack/react-query'

import { metaQuery } from '@/api/queries'
import { wholePath } from '@/lib/whole-path'

/**
 * A function giving a path the server shows from the workspace root whole, for a copy button: a shell the operator
 * pastes it into need not be in the workspace. It gives the path as shown until the server's meta is read.
 */
export function useWholePath(): (shown: string) => string {
    const meta = useQuery(metaQuery)
    const root = meta.data?.workspace_root
    return (shown) => wholePath(shown, root)
}
