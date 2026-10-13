/**
 * The path prefix the app is served under, without a trailing slash: '' at the root, '/canopy' behind a proxy.
 *
 * FastAPI writes it into index.html as <base href> (canopy/serve/spa.py). The Vite dev server writes none, so it is
 * ''. Read once: it cannot change without a reload.
 */
export const basePath: string = (() => {
    const href = document.querySelector('base')?.getAttribute('href')
    if (!href) {
        return ''
    }
    return new URL(href, globalThis.location.origin).pathname.replace(/\/+$/u, '')
})()

/** The URL of an API path, `/events` → `{basePath}/api/events`. */
export function apiUrl(path: `/${string}`): string {
    return `${basePath}/api${path}`
}
