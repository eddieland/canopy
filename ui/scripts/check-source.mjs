// Checks what oxlint and oxfmt do not (ui/AGENTS.md):
//
// - Under src/, a color is named, never written down (ui/DESIGN.md, "Tokens"). Refused everywhere but
//   src/styles/tokens.css: hex colors, CSS color functions, Tailwind's palette utilities (bg-zinc-800, text-white),
//   and the dark: variant. A theme difference belongs in tokens.css, not in a component.
// - Under src/, a corner is on the radius scale (ui/DESIGN.md, "Shape and space"): no arbitrary `rounded-[...]`.
// - No line in ui/ is longer than 120 characters, the repository's limit for every file type (AGENTS.md). A
//   formatter does not break a long string; split it (cn() and cva() take several).
import { readdirSync, readFileSync } from 'node:fs'
import { join, relative, resolve } from 'node:path'

const ui = resolve(import.meta.dirname, '..')
const src = join(ui, 'src')
const GENERATED = new Set(['src/routeTree.gen.ts', 'src/api/schema.gen.ts', 'package-lock.json'])
const EXEMPT = new Set(['src/styles/tokens.css', ...GENERATED])
const MAX_LINE = 120
const SKIP_DIRS = new Set(['node_modules', 'dist', 'test-results', 'playwright-report'])

const PALETTE =
    'slate|gray|zinc|neutral|stone|red|orange|amber|yellow|lime|green|emerald|teal|cyan|sky|blue|indigo|violet|' +
    'purple|fuchsia|pink|rose|black|white'
const PREFIXES =
    'bg|text|border(?:-[trblxy])?|ring|ring-offset|fill|stroke|outline|from|via|to|shadow|decoration|divide|caret|' +
    'placeholder|inset-shadow|drop-shadow'

const RULES = [
    { name: 'hex color', pattern: /(?<![\w&/])#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{3,4})\b/u },
    { name: 'color function', pattern: /\b(?:rgba?|hsla?|hwb|lab|lch|oklab|oklch|color)\(/u },
    {
        name: 'Tailwind palette color',
        pattern: new RegExp(`(?<![\\w-])(?:${PREFIXES})-(?:${PALETTE})(?:-\\d{2,3})?\\b`, 'u'),
    },
    { name: 'dark: variant', pattern: /(?<![\w-])dark:[\w![-]/u },
    {
        name: 'arbitrary radius',
        pattern: /(?<![\w-])rounded-\[/u,
        hint: 'use rounded-md, rounded-sm, or rounded-xs, the scale in src/styles/tokens.css',
    },
]

function* files(dir, pattern) {
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
        const path = join(dir, entry.name)
        if (entry.isDirectory()) {
            if (!SKIP_DIRS.has(entry.name)) {
                yield* files(path, pattern)
            }
        } else if (pattern.test(entry.name)) {
            yield path
        }
    }
}

const found = []
for (const path of files(src, /\.(?:css|ts|tsx)$/u)) {
    const name = relative(ui, path)
    if (EXEMPT.has(name)) {
        continue
    }
    readFileSync(path, 'utf8')
        .split('\n')
        .forEach((line, i) => {
            for (const rule of RULES) {
                const match = rule.pattern.exec(line)
                if (match) {
                    const hint = rule.hint ?? 'use a token from src/styles/tokens.css'
                    found.push(`${name}:${i + 1}: ${rule.name} \`${match[0]}\`; ${hint}`)
                }
            }
        })
}

for (const path of files(ui, /\.(?:css|ts|tsx|mjs|json|html|md|svg)$/u)) {
    const name = relative(ui, path)
    if (GENERATED.has(name)) {
        continue
    }
    readFileSync(path, 'utf8')
        .split('\n')
        .forEach((line, i) => {
            if (line.length > MAX_LINE && !/https?:\/\//u.test(line)) {
                found.push(`${name}:${i + 1}: ${line.length} characters; the limit is ${MAX_LINE}`)
            }
        })
}

if (found.length > 0) {
    console.error(found.join('\n'))
    process.exit(1)
}
console.log('check-source: every color is a token, every corner on the scale, every line fits in 120 columns.')
