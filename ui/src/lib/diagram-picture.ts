// A drawn diagram's picture taken out of the page (src/components/block-actions.tsx): the SVG the page shows
// (src/lib/diagram.ts), drawn on a canvas as a PNG at twice its pixels, on the surface it is drawn for, so it is opaque
// and reads on any page. It is made from the picture's own data URL, which the CSP's `img-src` allows; it imports no
// mermaid. A PNG is pixels: nothing in it can run, link, or load, so it is as inert as the image the page shows (D131).

/** How many of the PNG's pixels make one of the picture's. */
export const PNG_SCALE = 2

// What each kind of diagram is called in a file's name, by the kind mermaid read it as.
const KIND_WORDS: Partial<Record<string, string>> = {
    'flowchart-v2': 'flowchart',
    flowchart: 'flowchart',
    sequence: 'sequence',
    stateDiagram: 'state',
    classDiagram: 'class',
    class: 'class',
    er: 'er',
}

/** The kind `kind` names, as a file's name says it: `flowchart`, `sequence`, `state`, `class`, `er`. */
export function kindWord(kind: string): string {
    return KIND_WORDS[kind] ?? 'diagram'
}

/**
 * `svg`, a drawn diagram, as a PNG `PNG_SCALE` times its size, on `background`, a CSS color: the surface the picture is
 * drawn for, which the image itself leaves clear. Rejects when the browser cannot draw it.
 */
export async function diagramPng(svg: string, background: string): Promise<Blob> {
    const image = new Image()
    image.src = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`
    await image.decode()
    const canvas = document.createElement('canvas')
    canvas.width = Math.ceil(image.naturalWidth * PNG_SCALE)
    canvas.height = Math.ceil(image.naturalHeight * PNG_SCALE)
    const context = canvas.getContext('2d')
    if (context === null || canvas.width === 0 || canvas.height === 0) {
        throw new Error('the browser could not draw the picture')
    }
    context.fillStyle = background
    context.fillRect(0, 0, canvas.width, canvas.height)
    context.drawImage(image, 0, 0, canvas.width, canvas.height)
    return new Promise((resolve, reject) => {
        canvas.toBlob((blob) => {
            if (blob === null) {
                reject(new Error('the browser could not make the PNG'))
            } else {
                resolve(blob)
            }
        }, 'image/png')
    })
}

/** The surface a diagram's picture is drawn for, in the theme the page shows now: `--surface`, as mermaid drew it. */
export function diagramSurface(): string {
    return getComputedStyle(document.documentElement).getPropertyValue('--surface').trim()
}
