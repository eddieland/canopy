// The side nav's sections, each with a color of its own (ui/DESIGN.md, "Tokens"). A section's color is identity,
// never state: it marks the nav's icons, its highlight, and the trail over each page, and nothing in the data.

/**
 * Every section, by its path, in the nav's order: by how often the operator opens it, so what they work in is at the
 * top and what they check now and then is lower down. Settings is last and out of the nav: the rail's foot opens it.
 */
export const SECTIONS = [
    '/attention',
    '/tickets',
    '/tasks',
    '/pull-requests',
    '/runs',
    '/chores',
    '/reports',
    '/ticks',
    '/worktrees',
    '/memory',
    '/settings',
] as const

/** One section of the nav, by its path. */
export type Section = (typeof SECTIONS)[number]

/** Each section's name: its nav item's label and the first step of the trail over its pages. */
export const SECTION_LABEL: Record<Section, string> = {
    '/attention': 'Attention',
    '/runs': 'Runs',
    '/worktrees': 'Worktrees',
    '/tickets': 'Tickets',
    '/tasks': 'Tasks',
    '/pull-requests': 'Pull requests',
    '/chores': 'Chores',
    '/ticks': 'Ticks',
    '/reports': 'Reports',
    '/memory': 'Memory',
    '/settings': 'Settings',
}

// Full class names, written out, so Tailwind finds them. One entry per section; the types make a missing one an error.

/** Each section's color as text: its icon and the label over its pages. */
export const SECTION_TEXT: Record<Section, string> = {
    '/attention': 'text-section-attention',
    '/runs': 'text-section-runs',
    '/worktrees': 'text-section-worktrees',
    '/tickets': 'text-section-tickets',
    '/tasks': 'text-section-tasks',
    '/pull-requests': 'text-section-pull-requests',
    '/chores': 'text-section-chores',
    '/ticks': 'text-section-ticks',
    '/reports': 'text-section-reports',
    '/memory': 'text-section-memory',
    '/settings': 'text-section-settings',
}

/** Each section's color as a faint background: the nav's highlight on the section shown. */
export const SECTION_TINT: Record<Section, string> = {
    '/attention': 'bg-section-attention/16',
    '/runs': 'bg-section-runs/16',
    '/worktrees': 'bg-section-worktrees/16',
    '/tickets': 'bg-section-tickets/16',
    '/tasks': 'bg-section-tasks/16',
    '/pull-requests': 'bg-section-pull-requests/16',
    '/chores': 'bg-section-chores/16',
    '/ticks': 'bg-section-ticks/16',
    '/reports': 'bg-section-reports/16',
    '/memory': 'bg-section-memory/16',
    '/settings': 'bg-section-settings/16',
}

/** Each section's color as a solid fill: the bar at the nav highlight's left edge. */
export const SECTION_FILL: Record<Section, string> = {
    '/attention': 'bg-section-attention',
    '/runs': 'bg-section-runs',
    '/worktrees': 'bg-section-worktrees',
    '/tickets': 'bg-section-tickets',
    '/tasks': 'bg-section-tasks',
    '/pull-requests': 'bg-section-pull-requests',
    '/chores': 'bg-section-chores',
    '/ticks': 'bg-section-ticks',
    '/reports': 'bg-section-reports',
    '/memory': 'bg-section-memory',
    '/settings': 'bg-section-settings',
}
