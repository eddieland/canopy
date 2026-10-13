// The side nav's sections, each with a color of its own (ui/DESIGN.md, "Tokens"). A section's color is identity,
// never state: it marks the nav's icons, its highlight, and the label over each page, and nothing in the data.

export const SECTIONS = ['/attention', '/runs', '/worktrees', '/tickets', '/chores', '/ticks', '/settings'] as const

export type Section = (typeof SECTIONS)[number]

// Full class names, written out, so Tailwind finds them. One entry per section; the types make a missing one an error.

export const SECTION_TEXT: Record<Section, string> = {
    '/attention': 'text-section-attention',
    '/runs': 'text-section-runs',
    '/worktrees': 'text-section-worktrees',
    '/tickets': 'text-section-tickets',
    '/chores': 'text-section-chores',
    '/ticks': 'text-section-ticks',
    '/settings': 'text-section-settings',
}

export const SECTION_TINT: Record<Section, string> = {
    '/attention': 'bg-section-attention/16',
    '/runs': 'bg-section-runs/16',
    '/worktrees': 'bg-section-worktrees/16',
    '/tickets': 'bg-section-tickets/16',
    '/chores': 'bg-section-chores/16',
    '/ticks': 'bg-section-ticks/16',
    '/settings': 'bg-section-settings/16',
}

export const SECTION_FILL: Record<Section, string> = {
    '/attention': 'bg-section-attention',
    '/runs': 'bg-section-runs',
    '/worktrees': 'bg-section-worktrees',
    '/tickets': 'bg-section-tickets',
    '/chores': 'bg-section-chores',
    '/ticks': 'bg-section-ticks',
    '/settings': 'bg-section-settings',
}
