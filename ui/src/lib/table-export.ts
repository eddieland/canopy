// A table of a plan taken elsewhere as rows (src/components/block-actions.tsx): for a spreadsheet, as tab-separated
// text and an HTML table together, so Sheets, Excel, and Numbers each take the form they read, or as a CSV file. A plan
// is model text (TRUST_MODEL T1), and a spreadsheet runs a cell that starts with `=`, `+`, `-`, or `@` as a formula,
// which can reach out of the sheet; so such a cell is written as text, with the apostrophe every spreadsheet reads as
// "this is text" and shows nothing of, unless it is a plain number. The Markdown form is the plan's own characters and
// needs none of this.

/** A table's rows, its header row first, each cell its words. */
export type Rows = readonly (readonly string[])[]

// What starts a cell a spreadsheet would read as a formula: the four signs, and a tab or a return before one.
const FORMULA = /^[=+\-@\t\r]/u
// A number as written in a table: a sign, digits grouped or not, a fraction, a percent.
const NUMBER = /^[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?%?$/u

/** `words`, a cell, as a spreadsheet should read it: as text where it would otherwise run as a formula. */
export function spreadsheetCell(words: string): string {
    return FORMULA.test(words) && !NUMBER.test(words) ? `'${words}` : words
}

/** `rows` as tab-separated text, a row to a line, each cell on one line with no tab in it. */
export function tabSeparated(rows: Rows): string {
    return rows
        .map((row) => row.map((cell) => spreadsheetCell(oneLine(cell).replaceAll('\t', ' '))).join('\t'))
        .join('\n')
}

/** `rows` as an HTML table, its first row the header: what a spreadsheet pastes as cells, each escaped text. */
export function htmlTable(rows: Rows): string {
    const [head = [], ...body] = rows
    const rowsBelow = body.map((cells) => htmlRow(cells, 'td')).join('')
    return `<table><thead>${htmlRow(head, 'th')}</thead><tbody>${rowsBelow}</tbody></table>`
}

/**
 * `rows` as CSV (RFC 4180): a field quoted where it holds a comma, a quote, or a line's end, its quotes doubled, and
 * lines ended by CRLF.
 */
export function csv(rows: Rows): string {
    return `${rows.map((cells) => cells.map((cell) => csvField(cell)).join(',')).join('\r\n')}\r\n`
}

// A row of an HTML table, each cell in `tag`, as a spreadsheet should read it.
function htmlRow(cells: readonly string[], tag: 'th' | 'td'): string {
    return `<tr>${cells.map((cell) => `<${tag}>${escaped(spreadsheetCell(oneLine(cell)))}</${tag}>`).join('')}</tr>`
}

// A field of CSV, as a spreadsheet should read it, quoted where it must be.
function csvField(cell: string): string {
    const text = spreadsheetCell(cell)
    return /[",\r\n]/u.test(text) ? `"${text.replaceAll('"', '""')}"` : text
}

// `text` on one line, its line ends as spaces.
function oneLine(text: string): string {
    return text.replaceAll(/\r?\n/gu, ' ')
}

// `text` as HTML text, which writes no element.
function escaped(text: string): string {
    return text.replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;')
}
