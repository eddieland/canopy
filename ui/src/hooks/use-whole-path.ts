import { useQuery } from '@tanstack/react-query'

import { metaQuery } from '@/api/queries'
import { wholePath } from '@/lib/whole-path'

/**
 * A function giving a path the server shows from the workspace root whole, for a copy button: a shell the operator
 * pastes it into need not be in the workspace. Undefined until the server's meta gives the root, or while it cannot be
 * read, so a caller shows no copy button then rather than one that copies the short path.
 */
export function useWholePath(): ((shown: string) => string) | undefined {
    const root = useQuery(metaQuery).data?.workspace_root
    return root === undefined ? undefined : (shown) => wholePath(shown, root)
}
