/**
 * The id of the build this page was loaded from, which FastAPI writes into index.html as a meta tag
 * (canopy/serve/spa.py), or null under the Vite dev server, which writes none. Read once: a page keeps the build it
 * loaded until it reloads.
 */
export const pageBuild: string | null = buildIn(document)

/** The build id a document's meta tag holds, or null when it has none. */
export function buildIn(doc: Document): string | null {
    const content = doc.querySelector<HTMLMetaElement>('meta[name="canopy-build"]')?.content
    return content === undefined || content === '' ? null : content
}

/**
 * Whether the server serves a build other than the page's, as after an upgrade: only when both are known, so a page
 * from the dev server, a server whose UI is not built, or meta not read yet never asks for a reload.
 */
export function isOutdated(page: string | null, served: string | null | undefined): boolean {
    return page !== null && served !== null && served !== undefined && served !== page
}
