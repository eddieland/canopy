// A diagram a plan or a guide page writes as a Mermaid fence, drawn as SVG. A plan is model-written (TRUST_MODEL T1),
// so mermaid runs at its strictest: `strict` sanitizes labels with DOMPurify and drops `click` handlers, labels are SVG
// text rather than HTML (`htmlLabels: false`), and `secure` keeps a diagram's own front matter or `%%{init}%%` from
// setting any of it back, or the theme, layout, or CSS. Only the kinds a plan has use for are drawn; any other is
// refused as such. The SVG is a string for an `<img>` (src/lib/plan-diagram.ts, src/hooks/use-diagram.ts), where the
// browser runs no script, follows no link, and fetches nothing, so a gap in mermaid's sanitizer reaches nothing shown.
// A link a diagram writes (`click A href "…"`) is dropped from it all the same, its node drawn as any other.
// While it draws, mermaid lays the SVG out in the page, off screen, for a moment: there `strict` is the guard. Only
// this module imports mermaid, and only on demand.
//
// An image draws with its own colors and fonts, not the page's: the colors are read from the theme's tokens as each
// diagram is drawn, so a theme or palette changed redraws it, and the font is the system's, which the image can use,
// since one measured in the page's bundled font but drawn in another would clip its labels.
import mermaid from 'mermaid'
import type { MermaidConfig } from 'mermaid'

/** A diagram drawn: its SVG, and what kind it is (`flowchart-v2`, `sequence`, `stateDiagram`, `classDiagram`, `er`). */
export interface Drawn {
    /** The SVG, whole, for an image. */
    svg: string
    /** The kind mermaid read it as. */
    kind: string
    /** How wide it is drawn, in CSS pixels, as its SVG says; never shown much narrower (`diagram-image`). */
    width?: number | undefined
}

/** A diagram that was not drawn, and why, in a line for the operator. */
export interface NotDrawn {
    /** Why: mermaid's own message for a diagram it cannot read, or the kind it is for one not drawn here. */
    error: string
}

/** The Markdown fence's language that marks a diagram. */
export const DIAGRAM_LANGUAGE = 'mermaid'

// The kinds drawn, as mermaid names them: `graph` and `flowchart` are both `flowchart-v2`, `classDiagram` is
// `classDiagram` or its older renderer's `class`, and `erDiagram` is `er`.
const KINDS = new Set(['flowchart-v2', 'flowchart', 'sequence', 'stateDiagram', 'classDiagram', 'class', 'er'])
const KIND_NAMES = 'flowchart, sequenceDiagram, stateDiagram, classDiagram, and erDiagram'
// The configuration only this module may set: mermaid's own list, and what this module chooses, so a diagram cannot
// widen what it may do or change how it looks.
const SECURE = [
    'secure',
    'securityLevel',
    'startOnLoad',
    'maxTextSize',
    'maxEdges',
    'suppressErrorRendering',
    'htmlLabels',
    'theme',
    'themeVariables',
    'themeCSS',
    'darkMode',
    'fontFamily',
    'fontSize',
    'look',
    'layout',
    'elk',
    'flowchart',
    'sequence',
    'state',
    'class',
    'er',
]
// A plan is at most tens of thousands of characters; a diagram is a small part of it.
const MAX_TEXT = 20_000
// The font every system has, which an image can draw with. Not the page's IBM Plex: an image can use a font only if its
// SVG carries it whole, which would add more to each diagram than the diagram itself.
const FONT = 'ui-sans-serif, system-ui, sans-serif'
// One size for every label in every kind, the plan's table's: a sequence diagram's own default is larger.
const FONT_SIZE = 14
// The width a flowchart's label wraps at: wide enough that a module's name, `api: ReportQuery.iter_rows`, wraps between
// words, never inside one, which is all mermaid can do with a word longer than the width.
const WRAP_AT = 260
// A shape's corner: a step under the figure's own, so a node reads as held by it.
const RADIUS = 4
// The keyword that opens each kind mermaid reads but canopy does not draw, where it is not mermaid's own name for it:
// what the planner wrote, so `Not drawn:` names it as written.
const KEYWORDS: Partial<Record<string, string>> = {
    requirement: 'requirementDiagram',
    gitGraph: 'gitGraph',
    xychart: 'xychart-beta',
}
// The namespaces of an SVG's own elements, and of the `xlink:href` mermaid writes a link with.
const SVG = 'http://www.w3.org/2000/svg'
const XLINK = 'http://www.w3.org/1999/xlink'
// Why a picture is not shown when the browser cannot read it as SVG, as a plan's diagram says it too
// (src/lib/plan-diagram.ts).
const UNREADABLE = 'the browser cannot read its picture'

// How a diagram is read, drawn or not: at mermaid's strictest, whatever the diagram asks.
const READ: MermaidConfig = {
    startOnLoad: false,
    securityLevel: 'strict',
    secure: SECURE,
    htmlLabels: false,
    suppressErrorRendering: true,
    maxTextSize: MAX_TEXT,
}

let drawn = 0

/**
 * `source` drawn as SVG, in the theme the page shows now, or why it was not. One diagram at a time: mermaid draws in
 * the page, off screen, and keeps one configuration.
 */
export async function drawDiagram(source: string): Promise<Drawn | NotDrawn> {
    mermaid.initialize(configuration())
    try {
        const read = await kindOf(source)
        if (typeof read !== 'string') {
            return read
        }
        drawn += 1
        const { svg } = await mermaid.render(`plan-diagram-${drawn}`, source)
        const picture = withoutLinks(svg)
        return typeof picture === 'string' ? { svg: picture, kind: read, width: naturalWidth(picture) } : picture
    } catch (error) {
        return { error: firstLine(error) }
    }
}

/**
 * Why `source` would not be drawn, or `undefined` when it would: it is read as `drawDiagram` reads it, without being
 * drawn, so a test can hold a diagram to what is drawn where nothing can be laid out (the guide's, `guide.test.ts`).
 */
export async function readDiagram(source: string): Promise<NotDrawn | undefined> {
    mermaid.initialize(READ)
    try {
        const read = await kindOf(source)
        return typeof read === 'string' ? undefined : read
    } catch (error) {
        return { error: firstLine(error) }
    }
}

// The kind of diagram `source` is, or why it is not drawn here; mermaid throws on a diagram it cannot read.
async function kindOf(source: string): Promise<string | NotDrawn> {
    const { diagramType } = await mermaid.parse(source)
    return KINDS.has(diagramType)
        ? diagramType
        : { error: `${KEYWORDS[diagramType] ?? diagramType} is not drawn here, only ${KIND_NAMES}` }
}

function configuration(): MermaidConfig {
    const token = tokenReader()
    const background = token('--surface')
    const raised = token('--surface-raised')
    const ink = token('--foreground')
    const muted = token('--muted-foreground')
    // Each size is the one a node, a line, and a label are drawn at, without a layout's own `useMaxWidth`, which
    // would make the image as wide as whatever holds it rather than as wide as it is.
    const natural = { useMaxWidth: false }
    return {
        ...READ,
        theme: 'base',
        look: 'classic',
        layout: 'dagre',
        fontFamily: FONT,
        flowchart: { ...natural, wrappingWidth: WRAP_AT },
        // Its actors once, at the top: drawn again at the foot, they take a sixth of its height to say nothing new.
        sequence: {
            ...natural,
            mirrorActors: false,
            actorFontSize: FONT_SIZE,
            messageFontSize: FONT_SIZE,
            noteFontSize: FONT_SIZE,
            actorFontFamily: FONT,
            messageFontFamily: FONT,
            noteFontFamily: FONT,
        },
        state: natural,
        class: natural,
        er: natural,
        themeCSS: themeCss(background),
        themeVariables: {
            darkMode: document.documentElement.classList.contains('dark'),
            fontFamily: FONT,
            fontSize: `${FONT_SIZE}px`,
            background,
            primaryColor: raised,
            primaryTextColor: ink,
            primaryBorderColor: muted,
            secondaryColor: background,
            tertiaryColor: background,
            lineColor: muted,
            textColor: ink,
            titleColor: ink,
            edgeLabelBackground: background,
            clusterBkg: background,
            // A subgraph and a note are outlined as a node is, a subgraph's dashed: in `--border`, at 1.4:1 to the
            // canvas, they were too faint to see.
            clusterBorder: muted,
            noteBkgColor: raised,
            noteTextColor: ink,
            noteBorderColor: muted,
            actorBkg: raised,
            actorBorder: muted,
            actorTextColor: ink,
            actorLineColor: muted,
            signalColor: ink,
            signalTextColor: ink,
            labelBoxBkgColor: raised,
            labelBoxBorderColor: muted,
            labelTextColor: ink,
            loopTextColor: ink,
            stateBkg: raised,
            stateLabelColor: ink,
            transitionColor: muted,
            transitionLabelColor: ink,
            classText: ink,
            attributeBackgroundColorOdd: raised,
            attributeBackgroundColorEven: background,
        },
    }
}

// What every kind draws alike, as the document around it does: one corner and one line weight for every shape and
// edge, and a sequence's captions and messages lifted off the lifelines they cross by a halo of the canvas, as an
// edge's label sits on its own patch of it. Mermaid puts this before its own rules, so each wins by `!important`.
function themeCss(canvas: string): string {
    const shapes = '.node rect, .cluster rect, rect.actor, rect.note, .note rect, .statediagram-state rect, rect.basic'
    const lines = [
        '.flowchart-link, .edgePath .path, .transition, .messageLine0, .messageLine1',
        '.actor-line, .loopLine, .node rect, .node polygon, .node circle, .node path',
        '.cluster rect, rect.actor, rect.note, .statediagram-state rect, rect.basic',
    ].join(', ')
    return [
        `${shapes} { rx: ${RADIUS}px !important; ry: ${RADIUS}px !important; }`,
        `${lines} { stroke-width: 1px !important; }`,
        `.cluster rect { stroke-dasharray: 4 3 !important; }`,
        `.messageText, .loopText, .loopText tspan { paint-order: stroke; stroke: ${canvas} !important;`,
        ` stroke-width: 6px !important; stroke-linejoin: round; }`,
    ].join('\n')
}

// A token's color as `#rrggbb`, which mermaid can lighten and darken: tokens are written in oklch, which it cannot
// read, so each is painted on a pixel and read back.
function tokenReader(): (token: string) => string {
    const style = getComputedStyle(document.documentElement)
    const context = document.createElement('canvas').getContext('2d', { willReadFrequently: true })
    return (token) => {
        if (context === null) {
            return style.getPropertyValue(token).trim()
        }
        context.clearRect(0, 0, 1, 1)
        context.fillStyle = style.getPropertyValue(token).trim()
        context.fillRect(0, 0, 1, 1)
        const [red = 0, green = 0, blue = 0] = context.getImageData(0, 0, 1, 1).data
        return `#${[red, green, blue].map((channel) => channel.toString(16).padStart(2, '0')).join('')}`
    }
}

// `svg` with each link a diagram wrote (`click A href "…"`) turned into the group it wraps, which draws its node where
// it was, or why it cannot be shown. mermaid keeps such a link at `strict`, as an `<a>` with an `xlink:href` whose
// prefix it never declares, so the browser could not read the picture at all; and a link in a plan is not a link
// (D113). A picture with no link is returned as mermaid wrote it.
function withoutLinks(svg: string): string | NotDrawn {
    if (!/<a\b/u.test(svg)) {
        return svg
    }
    const declared = /^<svg\b[^>]*\sxmlns:xlink=/u.test(svg)
        ? svg
        : svg.replace(/^<svg\b/u, `<svg xmlns:xlink="${XLINK}"`)
    const picture = new DOMParser().parseFromString(declared, 'image/svg+xml')
    if (picture.querySelector('parsererror') !== null) {
        return { error: UNREADABLE }
    }
    // A list as it stands, which `getElementsByTagName`'s would not: it would shrink as each link is replaced.
    for (const link of picture.querySelectorAll('a')) {
        const group = picture.createElementNS(SVG, 'g')
        for (const attribute of link.attributes) {
            if (attribute.localName !== 'href' && attribute.localName !== 'target') {
                group.setAttributeNS(attribute.namespaceURI, attribute.name, attribute.value)
            }
        }
        group.append(...link.childNodes)
        link.replaceWith(group)
    }
    return new XMLSerializer().serializeToString(picture)
}

// The first line of what mermaid threw, which says where it could not read; the rest points at it in the source.
function firstLine(error: unknown): string {
    const message = error instanceof Error ? error.message : String(error)
    // Without the colon that points at the lines under it, or a full stop the caption adds.
    const line = message
        .split('\n', 1)[0]
        ?.trim()
        .replace(/[.:]+$/u, '')
    return line || 'mermaid could not read it'
}

// The width the SVG's root is drawn at, which mermaid writes as an attribute when a layout has no `useMaxWidth`.
function naturalWidth(svg: string): number | undefined {
    const width = /^<svg\b[^>]*?\swidth="(?<width>\d+(?:\.\d+)?)(?:px)?"/u.exec(svg)?.groups?.['width']
    return width === undefined ? undefined : Number(width)
}
