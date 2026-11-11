// A drawn diagram's SVG as a file of the operator's (D131). The page shows a diagram only as an `<img>`, which runs no
// script, follows no link, and fetches nothing; a saved file leaves that guard behind, since opened in a browser's tab,
// or from a wiki that serves it inline, it is a document of its own. So the file is never mermaid's SVG as it came: it
// is cut down to canopy's own lists, a second guard that does not rest on mermaid's sanitizer. Only the elements
// and attributes the drawn kinds use are kept; a link becomes the group it wraps; a reference reaches only within the
// file; and nothing in its CSS can load. A background goes under it, so it reads on any page. What the lists drop is
// returned too, so a test can hold them to what mermaid draws: a new element in a mermaid upgrade then fails a test
// rather than leave a part out of the picture the operator saves.

/** A diagram's SVG as it is saved, and what of it was dropped on the way. */
export interface SavedSvg {
    /** The file's text. */
    svg: string
    /** What was dropped, each as `element` or `element@attribute`, in the order met: none for what mermaid draws. */
    dropped: string[]
}

const SVG = 'http://www.w3.org/2000/svg'
// The elements a drawn diagram uses: shapes, text, their groups and definitions, and the filters mermaid shades with.
// Never `script`, `foreignObject`, `image`, `feImage`, or an animation; a link (`a`) is replaced by a group.
const ELEMENTS = new Set([
    'svg',
    'g',
    'defs',
    'style',
    'title',
    'desc',
    'symbol',
    'use',
    'marker',
    'clipPath',
    'pattern',
    'path',
    'rect',
    'circle',
    'ellipse',
    'line',
    'polyline',
    'polygon',
    'text',
    'tspan',
    'linearGradient',
    'radialGradient',
    'stop',
    'filter',
    'feDropShadow',
    'feGaussianBlur',
    'feOffset',
    'feFlood',
    'feComposite',
    'feMerge',
    'feMergeNode',
    'feBlend',
    'feColorMatrix',
])
// The attributes those use, by the name the file writes; a `data-` or `aria-` attribute is kept too. Never an event
// handler (`on…`). `href` is kept only to a fragment of the file (`#id`), below.
const ATTRIBUTES = new Set([
    'xmlns',
    'xmlns:xlink',
    'version',
    'id',
    'class',
    'style',
    'role',
    'title',
    'name',
    'transform',
    'viewBox',
    'preserveAspectRatio',
    'width',
    'height',
    'x',
    'y',
    'x1',
    'x2',
    'y1',
    'y2',
    'cx',
    'cy',
    'r',
    'rx',
    'ry',
    'd',
    'points',
    'pathLength',
    'dx',
    'dy',
    'rotate',
    'textLength',
    'lengthAdjust',
    'fill',
    'fill-opacity',
    'fill-rule',
    'clip-rule',
    'clip-path',
    'stroke',
    'stroke-width',
    'stroke-opacity',
    'stroke-dasharray',
    'stroke-dashoffset',
    'stroke-linecap',
    'stroke-linejoin',
    'stroke-miterlimit',
    'opacity',
    'font-family',
    'font-size',
    'font-style',
    'font-weight',
    'text-anchor',
    'dominant-baseline',
    'alignment-baseline',
    'text-decoration',
    'letter-spacing',
    'visibility',
    'display',
    'offset',
    'stop-color',
    'stop-opacity',
    'gradientUnits',
    'gradientTransform',
    'spreadMethod',
    'fx',
    'fy',
    'patternUnits',
    'patternContentUnits',
    'patternTransform',
    'clipPathUnits',
    'marker-start',
    'marker-mid',
    'marker-end',
    'markerWidth',
    'markerHeight',
    'markerUnits',
    'refX',
    'refY',
    'orient',
    'filterUnits',
    'primitiveUnits',
    'flood-color',
    'flood-opacity',
    'stdDeviation',
    'in',
    'in2',
    'result',
    'operator',
    'mode',
    'type',
    'values',
    'k1',
    'k2',
    'k3',
    'k4',
])
// A reference within the file: `#id`, or `url(#id)`, quoted or not.
const FRAGMENT = /^#[\w.:-]*$/u
// A `url(…)` that reaches outside the file, in CSS or an attribute's value.
const OUTSIDE = /url\(\s*(?!['"]?#)[^)]*\)/iu
// The functions the CSS of a saved picture may call: its colors, a shadow, a transform's steps, a selector's own, and
// `url()`, which reaches only within the file (`OUTSIDE`). Any other, `image-set()` among them, may load elsewhere.
const CSS_FUNCTIONS = new Set([
    'url',
    'rgb',
    'rgba',
    'hsl',
    'hsla',
    'drop-shadow',
    'translate',
    'translatex',
    'translatey',
    'scale',
    'scalex',
    'scaley',
    'rotate',
    'matrix',
    'not',
    'is',
    'where',
    'nth-child',
    'nth-of-type',
])
// The attributes whose values are CSS, held to the same rules as a stylesheet.
const CSS_VALUED = new Set([
    'style',
    'fill',
    'stroke',
    'filter',
    'clip-path',
    'marker-start',
    'marker-mid',
    'marker-end',
    'transform',
    'gradientTransform',
    'patternTransform',
    'font-family',
    'stop-color',
    'flood-color',
])

/**
 * `svg`, a drawn diagram as the page shows it, made ready to be saved: only what canopy's lists keep, its links groups,
 * on `background`, a CSS color, under it. An `svg` the browser cannot read is refused.
 */
export function savedSvg(svg: string, background: string): SavedSvg {
    const picture = new DOMParser().parseFromString(svg, 'image/svg+xml')
    const root = picture.documentElement
    if (picture.querySelector('parsererror') !== null || root.namespaceURI !== SVG || root.localName !== 'svg') {
        throw new Error('the browser cannot read its picture')
    }
    const dropped: string[] = []
    keep(root, dropped)
    root.prepend(backdrop(picture, root, background))
    // The root alone, which leaves out what sits beside it: a doctype, or an `<?xml-stylesheet?>` that would load.
    return { svg: new XMLSerializer().serializeToString(root), dropped }
}

// Keeps of `element` and what it holds only what the lists do, saying what it drops in `dropped`.
function keep(element: Element, dropped: string[]): void {
    // By their names, a list as it stands: the element's own would shrink as each is removed.
    for (const name of element.getAttributeNames()) {
        const value = element.getAttribute(name) ?? ''
        if (!keeps(name, value) || OUTSIDE.test(value) || (CSS_VALUED.has(name) && !plainCss(value))) {
            dropped.push(`${element.localName}@${name}`)
            element.removeAttribute(name)
        }
    }
    if (element.localName === 'style' && !plainCss(element.textContent)) {
        dropped.push('style')
        element.textContent = ''
    }
    // Each child, its next found before it is replaced or removed; of what is not an element, text alone stays.
    let child = element.firstChild
    while (child !== null) {
        const next = child.nextSibling
        if (!(child instanceof Element)) {
            if (child.nodeType !== Node.TEXT_NODE && child.nodeType !== Node.CDATA_SECTION_NODE) {
                dropped.push(
                    child.nodeType === Node.PROCESSING_INSTRUCTION_NODE ? '#processing-instruction' : child.nodeName,
                )
                child.remove()
            }
        } else if (child.namespaceURI === SVG && child.localName === 'a') {
            dropped.push('a')
            const group = child.ownerDocument.createElementNS(SVG, 'g')
            for (const attribute of child.attributes) {
                group.setAttributeNS(attribute.namespaceURI, attribute.name, attribute.value)
            }
            group.append(...child.childNodes)
            child.replaceWith(group)
            keep(group, dropped)
        } else if (child.namespaceURI !== SVG || !ELEMENTS.has(child.localName)) {
            dropped.push(child.localName)
            child.remove()
        } else {
            keep(child, dropped)
        }
        child = next
    }
}

// Whether `css` is CSS that loads nothing and hides nothing: no escape (`\75rl(` is `url(`), no at-rule but
// `@keyframes`, no function but those listed, and no `url()` outside the file. Mermaid's own holds none of these, so
// CSS that does is dropped whole rather than mended.
function plainCss(css: string): boolean {
    if (css.includes('\\') || OUTSIDE.test(css)) {
        return false
    }
    for (const [rule] of css.matchAll(/@[\w-]*/gu)) {
        if (rule.toLowerCase() !== '@keyframes') {
            return false
        }
    }
    for (const [, name = ''] of css.matchAll(/([\w-]*)\(/gu)) {
        if (!CSS_FUNCTIONS.has(name.toLowerCase())) {
            return false
        }
    }
    return true
}

// Whether the lists keep the attribute `name`, of `value`: one they name, a `data-` or `aria-` one, or a reference
// within the file.
function keeps(name: string, value: string): boolean {
    if (name === 'href' || name === 'xlink:href') {
        return FRAGMENT.test(value.trim())
    }
    return ATTRIBUTES.has(name) || /^(?:data|aria)-[\w-]+$/u.test(name)
}

// A rectangle of `background` under all the picture draws: over its view box where it has one, else its whole size.
function backdrop(picture: Document, root: Element, background: string): Element {
    const rect = picture.createElementNS(SVG, 'rect')
    const box = (root.getAttribute('viewBox') ?? '')
        .trim()
        .split(/[\s,]+/u)
        .map((part) => Number.parseFloat(part))
    const [x, y, width, height] = box
    if (box.length === 4 && box.every((part) => Number.isFinite(part))) {
        rect.setAttribute('x', String(x))
        rect.setAttribute('y', String(y))
        rect.setAttribute('width', String(width))
        rect.setAttribute('height', String(height))
    } else {
        rect.setAttribute('width', '100%')
        rect.setAttribute('height', '100%')
    }
    rect.setAttribute('fill', background)
    return rect
}
