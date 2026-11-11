import { describe, expect, it } from 'vitest'

import { csv, htmlTable, spreadsheetCell, tabSeparated } from './table-export'

const ROWS = [
    ['Repository', 'File', 'Why'],
    ['web', 'app/reports/export.py', 'the new route, with "quotes"'],
    ['api', '=HYPERLINK("https://example.com","x")', '-3'],
]

describe('a cell for a spreadsheet', () => {
    it.each([
        ['=HYPERLINK("https://example.com","x")', `'=HYPERLINK("https://example.com","x")`],
        ['+cmd|calc', "'+cmd|calc"],
        ['@SUM(A1:A2)', "'@SUM(A1:A2)"],
        ['-', "'-"],
        ['\t=1', "'\t=1"],
    ])('%j is written as text', (cell, written) => {
        expect(spreadsheetCell(cell)).toBe(written)
    })

    it.each(['-3', '+1', '1,234.5', '-0.25', '12%', 'web', 'a = b', ''])('%j is written as it is', (cell) => {
        expect(spreadsheetCell(cell)).toBe(cell)
    })
})

describe("a table's rows", () => {
    it('as tab-separated text: a row to a line, no tab or line end inside a cell', () => {
        expect(
            tabSeparated([
                ['a\tb', 'c\nd'],
                ['=1', '2'],
            ]),
        ).toBe("a b\tc d\n'=1\t2")
    })

    it('as an HTML table: the first row its head, every cell escaped text', () => {
        expect(
            htmlTable([
                ['<b>', 'x & y'],
                ['"q"', '=1'],
            ]),
        ).toBe(
            '<table><thead><tr><th>&lt;b&gt;</th><th>x &amp; y</th></tr></thead>' +
                "<tbody><tr><td>&quot;q&quot;</td><td>'=1</td></tr></tbody></table>",
        )
    })

    it('as CSV: quoted where it must be, quotes doubled, CRLF, a formula written as text', () => {
        expect(csv(ROWS)).toBe(
            [
                'Repository,File,Why',
                'web,app/reports/export.py,"the new route, with ""quotes"""',
                `api,"'=HYPERLINK(""https://example.com"",""x"")",-3`,
                '',
            ].join('\r\n'),
        )
    })
})
