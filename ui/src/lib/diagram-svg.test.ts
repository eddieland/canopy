import { describe, expect, it } from 'vitest'

import { savedSvg } from './diagram-svg'

const SVG = 'http://www.w3.org/2000/svg'

// A picture as mermaid draws one: a style scoped to its id, markers, a gradient, a filter, groups, shapes, and text,
// with the attributes each kind uses.
const DRAWN = [
    `<svg xmlns="${SVG}" id="plan-diagram-3" width="450" height="376" viewBox="-50 -10 450 376"`,
    ' class="flowchart" role="graphics-document document" aria-roledescription="flowchart-v2">',
    '<style>#plan-diagram-3{font-family:ui-sans-serif;fill:navy;}',
    '#plan-diagram-3 .node rect{stroke:url(#plan-diagram-3-gradient);}</style>',
    '<g><marker id="m" class="marker" viewBox="0 0 10 10" refX="5" refY="5" markerUnits="userSpaceOnUse"',
    ' markerWidth="8" markerHeight="8" orient="auto"><path d="M 0 0 L 10 5 L 0 10 z" style="stroke-width: 1;"/>',
    '</marker><g class="root"><path d="M1,1L2,2" data-edge="true" data-points="W10=" marker-end="url(#m)"/>',
    '<g class="node" id="n" title="a tooltip" transform="translate(98, 31.5)"><rect x="-90" y="-23.5" width="180"',
    ' height="47"/><circle cx="5" cy="5" r="5"/><polygon points="0,7 11.5,14 11.5,0"/>',
    '<line x1="0" x2="1" y1="0" y2="1" stroke-width="1"/><text y="-10.1" text-anchor="middle">',
    '<tspan class="row" x="0" dy="1.1em" font-weight="normal">canopy</tspan></text></g></g></g>',
    '<defs><filter id="f" height="130%" width="130%"><feDropShadow dx="4" dy="4" stdDeviation="0"',
    ' flood-opacity="0.06" flood-color="black"/></filter></defs>',
    '<linearGradient id="plan-diagram-3-gradient" gradientUnits="objectBoundingBox" x1="0%" y1="0%" x2="100%"',
    ' y2="0%"><stop offset="0%" stop-color="gray" stop-opacity="1"/></linearGradient></svg>',
].join('')

// The saved file read back.
function read(svg: string): Document {
    return new DOMParser().parseFromString(svg, 'image/svg+xml')
}

// The names of the elements of `picture`, in document order.
function names(picture: Document): string[] {
    return [...picture.querySelectorAll('*')].map((element) => element.localName)
}

describe('a diagram saved as an SVG', () => {
    it('keeps everything mermaid draws, over a background as large as its view box', () => {
        const { svg, dropped } = savedSvg(DRAWN, 'white')
        expect(dropped).toEqual([])
        const saved = read(svg)
        const drawn = read(DRAWN)
        expect(names(saved)).toEqual(['svg', 'rect', ...names(drawn).slice(1)])
        const backdrop = saved.documentElement.firstElementChild
        expect(['x', 'y', 'width', 'height', 'fill'].map((name) => backdrop?.getAttribute(name))).toEqual([
            '-50',
            '-10',
            '450',
            '376',
            'white',
        ])
        expect(saved.querySelector('style')?.textContent).toContain('url(#plan-diagram-3-gradient)')
        expect(saved.querySelector('path[data-edge]')?.getAttribute('marker-end')).toBe('url(#m)')
    })

    it('covers its whole size with the background when it has no view box', () => {
        const { svg } = savedSvg(`<svg xmlns="${SVG}" width="10" height="10"><rect width="1" height="1"/></svg>`, 'x')
        const backdrop = read(svg).documentElement.firstElementChild
        expect([backdrop?.getAttribute('width'), backdrop?.getAttribute('height')]).toEqual(['100%', '100%'])
    })

    it('drops what could run, load, or link, and says what it dropped', () => {
        const hostile = [
            `<svg xmlns="${SVG}" xmlns:xlink="http://www.w3.org/1999/xlink" onload="go()" viewBox="0 0 10 10">`,
            '<style>@import url(https://example.com/a.css); g { fill: url(https://example.com/x.svg#p) }',
            ' rect { stroke: url(#ok) }</style>',
            '<script>window.pwned = 1</script>',
            '<a xlink:href="https://example.com" target="_blank" transform="translate(1, 2)"><rect width="1"/></a>',
            '<g onclick="go()" style="fill: url(https://example.com/f)"><circle r="1"/></g>',
            '<foreignObject><div xmlns="http://www.w3.org/1999/xhtml">hi</div></foreignObject>',
            '<image href="https://example.com/p.png"/>',
            '<use href="https://example.com/s.svg#a"/><use href="#ok"/>',
            '<filter id="f"><feImage href="https://example.com/i.png"/></filter>',
            '<animate attributeName="x"/>',
            '</svg>',
        ].join('')
        const { svg, dropped } = savedSvg(hostile, 'black')
        expect(dropped).toEqual([
            'svg@onload',
            'style@import-or-url',
            'script',
            'a',
            'g@xlink:href',
            'g@target',
            'g@onclick',
            'g@style',
            'foreignObject',
            'image',
            'use@href',
            'feImage',
            'animate',
        ])
        expect(svg).not.toMatch(/example\.com|<script|<a\b|onload|onclick|foreignObject|<image|feImage|@import/iu)
        const saved = read(svg)
        // The link's group keeps where it drew its node, and what it held.
        expect(saved.querySelector('g[transform="translate(1, 2)"] > rect')).not.toBeNull()
        expect([...saved.querySelectorAll('use')].map((use) => use.getAttribute('href'))).toEqual([null, '#ok'])
        expect(saved.querySelector('style')?.textContent).toContain('url(#ok)')
    })

    it('refuses a picture the browser cannot read', () => {
        expect(() => savedSvg('<svg><a xlink:href="x"/></svg>', 'black')).toThrow('the browser cannot read its picture')
    })
})
