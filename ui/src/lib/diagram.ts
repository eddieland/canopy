// A diagram a plan writes as a Mermaid fence, drawn as SVG. A plan is model-written (TRUST_MODEL T1), so mermaid runs
// at its strictest: `strict` sanitizes labels with DOMPurify and drops `click` handlers, labels are SVG text rather
// than HTML (`htmlLabels: false`), and `secure` keeps a diagram's own front matter or `%%{init}%%` from setting any of
// it back, or the theme, layout, or CSS. Only the kinds a plan has use for are drawn; any other is refused as such. The
// SVG is a string for an `<img>` (src/lib/plan-diagram.ts), where the browser runs no script, follows no link, and
// fetches nothing, so a gap in mermaid's sanitizer still reaches nothing on the page. Only this module imports
// mermaid, and only on demand.
//
// An image draws with its own colors and fonts, not the page's: the colors are read from the theme's tokens as each
// diagram is drawn, so a theme or palette changed redraws it, and the font is the system's, which the image can use,
// since one measured in the page's bundled font but drawn in another would clip its labels.
import mermaid from 'mermaid'
import type { MermaidConfig } from 'mermaid'

/** A diagram drawn: its SVG, and what kind it is (`flowchart-v2`, `sequence`, `stateDiagram`). */
export interface Drawn {
    /** The SVG, whole, for an image. */
    svg: string
    /** The kind mermaid read it as. */
    kind: string
}

/** A diagram that was not drawn, and why, in a line for the operator. */
export interface NotDrawn {
    /** Why: mermaid's own message for a diagram it cannot read, or the kind it is for one not drawn here. */
    error: string
}

/** The Markdown fence's language that marks a diagram. */
export const DIAGRAM_LANGUAGE = 'mermaid'

// The kinds drawn, as mermaid names them: `graph` and `flowchart` are both `flowchart-v2`.
const KINDS = new Set(['flowchart-v2', 'flowchart', 'sequence', 'stateDiagram'])
const KIND_NAMES = 'flowchart, sequenceDiagram, and stateDiagram'
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
]
// A plan is at most tens of thousands of characters; a diagram is a small part of it.
const MAX_TEXT = 20_000
// The font every system has, which an image can draw with.
const FONT = 'ui-sans-serif, system-ui, sans-serif'

let drawn = 0

/**
 * `source` drawn as SVG, in the theme the page shows now, or why it was not. One diagram at a time: mermaid draws in
 * the page, off screen, and keeps one configuration.
 */
export async function drawDiagram(source: string): Promise<Drawn | NotDrawn> {
    mermaid.initialize(configuration())
    try {
        const { diagramType } = await mermaid.parse(source)
        if (!KINDS.has(diagramType)) {
            return { error: `a ${diagramType} diagram is not drawn here, only ${KIND_NAMES}` }
        }
        drawn += 1
        const { svg } = await mermaid.render(`plan-diagram-${drawn}`, source)
        return { svg, kind: diagramType }
    } catch (error) {
        return { error: firstLine(error) }
    }
}

function configuration(): MermaidConfig {
    const token = tokenReader()
    const background = token('--surface')
    const raised = token('--surface-raised')
    const ink = token('--foreground')
    const muted = token('--muted-foreground')
    const edge = token('--border')
    // Each size is the one a node, a line, and a label are drawn at, without a layout's own `useMaxWidth`, which
    // would make the image as wide as whatever holds it rather than as wide as it is.
    const natural = { useMaxWidth: false }
    return {
        startOnLoad: false,
        securityLevel: 'strict',
        secure: SECURE,
        htmlLabels: false,
        suppressErrorRendering: true,
        maxTextSize: MAX_TEXT,
        theme: 'base',
        look: 'classic',
        layout: 'dagre',
        fontFamily: FONT,
        flowchart: natural,
        sequence: natural,
        state: natural,
        themeVariables: {
            darkMode: document.documentElement.classList.contains('dark'),
            fontFamily: FONT,
            fontSize: '14px',
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
            clusterBorder: edge,
            noteBkgColor: raised,
            noteTextColor: ink,
            noteBorderColor: edge,
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
        },
    }
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
