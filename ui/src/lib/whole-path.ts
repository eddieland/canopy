/**
 * A path the server shows from the workspace root, whole, for pasting into a shell anywhere: joined to `root`. A path
 * outside the workspace, which the server sends whole already, stays as it is.
 */
export function wholePath(shown: string, root: string): string {
    if (shown.startsWith('/')) {
        return shown
    }
    const base = root.replace(/\/+$/u, '')
    return shown === '.' ? base || '/' : `${base}/${shown}`
}
