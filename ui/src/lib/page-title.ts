// The browser tab's title (ui/DESIGN.md, "The tab"). A tab is narrow and truncates from the right, so what tells one
// tab from another comes first: what blocks on the operator, then the page, then the app.

/**
 * A page's title in the browser tab: how many attention items block work, when any do, then the page's name, then
 * `canopy`, as in `(3) PROJ-12 Fix the login · canopy`. Without a name, just the count and `canopy`.
 */
export function pageTitle(name: string | undefined, attention: number | undefined): string {
    const count = attention === undefined || attention === 0 ? '' : `(${attention}) `
    return `${count}${name === undefined || name === '' ? '' : `${name} · `}canopy`
}
