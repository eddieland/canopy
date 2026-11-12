import { useEffect, useState } from 'react'

/**
 * The first in page order of the sections `ids` names (space-separated) whose element crosses the top half of the
 * page's scroll, by its id: the one a page's index marks current. Undefined until the page has scrolled one into view,
 * or where the browser cannot say.
 */
export function useFirstInView(ids: string): string | undefined {
    const [shown, setShown] = useState<ReadonlySet<string>>(new Set())
    useEffect(() => {
        if (typeof IntersectionObserver === 'undefined') {
            return
        }
        const observer = new IntersectionObserver(
            (entries) =>
                setShown((was) => {
                    const now = new Set(was)
                    for (const entry of entries) {
                        if (entry.isIntersecting) {
                            now.add(entry.target.id)
                        } else {
                            now.delete(entry.target.id)
                        }
                    }
                    return now
                }),
            // The top half of the scroll: a section counts once it reaches there, and until it leaves the top.
            { rootMargin: '0px 0px -50% 0px' },
        )
        for (const id of ids.split(' ').filter((one) => one !== '')) {
            const section = document.querySelector(`#${CSS.escape(id)}`)
            if (section !== null) {
                observer.observe(section)
            }
        }
        return () => observer.disconnect()
    }, [ids])
    return ids.split(' ').find((id) => shown.has(id))
}
