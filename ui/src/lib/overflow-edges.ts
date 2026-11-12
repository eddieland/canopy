// Which edges of a box that scrolls sideways have more past them, as `data-more-start` and `data-more-end` on the box,
// so its CSS fades those edges (`edge-fade`, src/index.css) and the operator sees there is more without a scrollbar,
// which macOS hides until a scroll. Kept current as the box scrolls, as it or what it holds changes size, and as an
// image in it loads.

// A pixel either way, which a scroll position rounded on a high-density screen can be off by.
const SLACK = 1

/**
 * Marks `box`, which scrolls sideways, with the edges that have more past them, now and as it scrolls or changes size.
 * Returns what stops it.
 */
export function markOverflowEdges(box: HTMLElement): () => void {
    const mark = (): void => {
        const { scrollLeft, scrollWidth, clientWidth } = box
        box.toggleAttribute('data-more-start', scrollLeft > SLACK)
        box.toggleAttribute('data-more-end', scrollLeft + clientWidth < scrollWidth - SLACK)
    }
    mark()
    box.addEventListener('scroll', mark, { passive: true })
    // What it holds is watched too: a box's own size stays put while a picture in it loads, or a table in it grows.
    const sizes = new ResizeObserver(mark)
    sizes.observe(box)
    for (const held of box.children) {
        sizes.observe(held)
    }
    box.addEventListener('load', mark, { capture: true })
    return () => {
        box.removeEventListener('scroll', mark)
        box.removeEventListener('load', mark, { capture: true })
        sizes.disconnect()
    }
}
