// Checks the shape of src/'s imports, which oxlint cannot say per directory (ui/AGENTS.md, "Imports go down"):
//
// - Each directory of src/ is a layer, and imports only from itself and the layers LAYERS names for it, so imports go
//   down: the API's client and types, then pure logic, then hooks, then components, then the shell and the routes
//   that compose them. A file is in the deepest layer whose directory holds it, so src/components/ui is a layer apart
//   from src/components. Type imports count: a type from a layer above is a dependency on it all the same, but for
//   the route tree's, which any layer may name a route by. A test is held to none of this: it may render what sits
//   above the code it tests, to see what that code did.
// - A library held to a few files (ui/AGENTS.md, "Stack") is imported nowhere else, a test of those files aside.
//   Type imports do not count here: they load nothing, so they bring no library into a page's chunk.
import { readdirSync, readFileSync } from 'node:fs'
import { join, relative, resolve } from 'node:path'

const ui = resolve(import.meta.dirname, '..')
const GENERATED = new Set(['src/routeTree.gen.ts', 'src/api/schema.gen.ts'])

// Each layer, and the layers (or single files) it may import from besides itself. `src` is the app's wiring at the
// top: main.tsx, the route tree, and test-utils.ts.
const LAYERS = new Map(
    Object.entries({
        'src/guide': [],
        'src/styles': [],
        // The client reads the base path, which the router and links read too.
        'src/api': ['src/lib/base.ts'],
        'src/lib': ['src/api', 'src/guide'],
        'src/theme': ['src/lib'],
        'src/hooks': ['src/api', 'src/lib'],
        // shadcn's wrappers: Radix and cmdk, styled. They know nothing of canopy's data.
        'src/components/ui': ['src/lib'],
        'src/components': ['src/api', 'src/lib', 'src/theme', 'src/hooks', 'src/components/ui'],
        // The frame every page sits in: the header, the rail, the nav, and what they open.
        'src/components/shell': ['src/api', 'src/lib', 'src/theme', 'src/hooks', 'src/components/ui', 'src/components'],
        'src/routes': [
            'src/api',
            'src/lib',
            'src/theme',
            'src/hooks',
            'src/components/ui',
            'src/components',
            'src/components/shell',
        ],
        src: [
            'src/guide',
            'src/styles',
            'src/api',
            'src/lib',
            'src/theme',
            'src/hooks',
            'src/components/ui',
            'src/components',
            'src/components/shell',
            'src/routes',
        ],
    }),
)

// Generated types any layer may import: the route tree's, which name a route by its id (src/lib/guide.ts).
const TYPES_ANYWHERE = new Set(['src/routeTree.gen'])

const LIBRARIES = [
    {
        name: 'Tiptap',
        pattern: /^(?:@tiptap\/|prosemirror-)/u,
        files: /^src\/(?:lib\/plan-[\w-]+|components\/plan-editor)(?:\.test)?\.tsx?$/u,
        where: 'src/lib/plan-*.ts and src/components/plan-editor.tsx (D120)',
    },
    {
        name: 'Shiki',
        pattern: /^shiki(?:\/|$)/u,
        files: /^src\/lib\/(?:highlight|languages)(?:\.test)?\.ts$/u,
        where: 'src/lib/highlight.ts and src/lib/languages.ts (D121)',
    },
    {
        name: 'jsdiff',
        pattern: /^diff(?:\/|$)/u,
        files: /^src\/lib\/plan-diff(?:\.test)?\.ts$/u,
        where: 'src/lib/plan-diff.ts',
    },
]

// `import ... from 'x'` and `export ... from 'x'`, over lines; a bare `import 'x'`; and `import('x')`.
const STATIC = /^[ \t]*(?:import|export)\b(?<type>[ \t]+type\b)?[^'"`;]*?\bfrom[ \t]*['"](?<spec>[^'"]+)['"]/gmu
const BARE = /^[ \t]*import[ \t]*['"](?<spec>[^'"]+)['"]/gmu
const DYNAMIC = /\bimport\(\s*['"](?<spec>[^'"]+)['"]\s*\)/gu

function* files(dir) {
    for (const entry of readdirSync(dir, { withFileTypes: true })) {
        const path = join(dir, entry.name)
        if (entry.isDirectory()) {
            yield* files(path)
        } else if (/\.tsx?$/u.test(entry.name)) {
            yield path
        }
    }
}

/** The deepest layer whose directory holds `path`, or undefined outside src/. */
function layerOf(path) {
    let found
    for (const dir of LAYERS.keys()) {
        if ((path === dir || path.startsWith(`${dir}/`)) && (found === undefined || dir.length > found.length)) {
            found = dir
        }
    }
    return found
}

/** Each import in `source`: its specifier, whether it imports types alone, and its line. */
function* importsOf(source) {
    const text = String(source)
    for (const pattern of [STATIC, BARE, DYNAMIC]) {
        for (const match of text.matchAll(pattern)) {
            const line = text.slice(0, match.index).split('\n').length
            yield { spec: match.groups?.['spec'] ?? '', typeOnly: match.groups?.['type'] !== undefined, line }
        }
    }
}

/** The path under ui/ a local specifier names, without its extension or query; undefined for a package. */
function target(spec, from) {
    const path = String(spec).replace(/\?.*$/su, '')
    if (path.startsWith('@/')) {
        return `src/${path.slice(2)}`
    }
    if (path.startsWith('.')) {
        return relative(ui, resolve(ui, from, '..', path))
            .split('\\')
            .join('/')
    }
}

/** Whether a file in `layer` may import `path`, which is in `to`. */
function allowed(layer, path, to, typeOnly) {
    const may = LAYERS.get(layer) ?? []
    return (
        to === layer ||
        may.includes(to) ||
        may.some((file) => /\.tsx?$/u.test(file) && path === file.replace(/\.tsx?$/u, '')) ||
        (typeOnly === true && TYPES_ANYWHERE.has(path))
    )
}

const found = []
for (const file of files(join(ui, 'src'))) {
    const name = relative(ui, file).split('\\').join('/')
    if (GENERATED.has(name)) {
        continue
    }
    const layer = layerOf(name)
    const test = /\.test\.tsx?$/u.test(name)
    for (const { spec, typeOnly, line } of importsOf(readFileSync(file, 'utf8'))) {
        const path = target(spec, name)
        if (path === undefined) {
            const library = LIBRARIES.find((held) => held.pattern.test(spec))
            if (library && !typeOnly && !library.files.test(name)) {
                found.push(`${name}:${line}: imports ${spec}; ${library.name} is imported only by ${library.where}`)
            }
            continue
        }
        const to = layerOf(path)
        if (!test && to !== undefined && !allowed(layer, path, to, typeOnly)) {
            const may = [layer, ...(LAYERS.get(layer) ?? [])].join(', ')
            found.push(`${name}:${line}: imports ${spec}; ${layer} imports only from ${may}`)
        }
    }
}

if (found.length > 0) {
    console.error(found.join('\n'))
    process.exit(1)
}
console.log('check-imports: every import goes down the layers, every held library stays in its files.')
