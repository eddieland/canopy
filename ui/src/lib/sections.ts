// The side nav's sections, each with a color of its own (ui/DESIGN.md, "Tokens"). A section's color is identity,
// never state: it marks the nav's icons, its highlight and active label, and the trail over each page, and nothing in
// the data.

/**
 * Every section, by its path, in the nav's order: by how often the operator opens it, so what they work in is at the
 * top and what they check now and then is lower down. Settings is last and out of the nav: the rail's foot opens it.
 * The header's aurora (`index.css`) runs through the nav's colors in this order: a change here changes it too.
 */
export const SECTIONS = [
    '/attention',
    '/tickets',
    '/tasks',
    '/pull-requests',
    '/runs',
    '/chores',
    '/reports',
    '/memory',
    '/settings',
] as const

/** One section of the nav, by its path. */
export type Section = (typeof SECTIONS)[number]

/** Each section's name: its nav item's label and the first step of the trail over its pages. */
export const SECTION_LABEL: Record<Section, string> = {
    '/attention': 'Attention',
    '/runs': 'Runs',
    '/tickets': 'Tickets',
    '/tasks': 'Tasks',
    '/pull-requests': 'Pull requests',
    '/chores': 'Chores',
    '/reports': 'Reports',
    '/memory': 'Memory',
    '/settings': 'Settings',
}

// Full class names, written out, so Tailwind finds them. One entry per section; the types make a missing one an error.

/** Each section's color as text: its icon, its nav label while it is shown, and the label over its pages. */
export const SECTION_TEXT: Record<Section, string> = {
    '/attention': 'text-section-attention',
    '/runs': 'text-section-runs',
    '/tickets': 'text-section-tickets',
    '/tasks': 'text-section-tasks',
    '/pull-requests': 'text-section-pull-requests',
    '/chores': 'text-section-chores',
    '/reports': 'text-section-reports',
    '/memory': 'text-section-memory',
    '/settings': 'text-section-settings',
}

/** Each section's color as a tint: the nav's highlight on the section shown, under its label in that color. */
export const SECTION_TINT: Record<Section, string> = {
    '/attention': 'bg-section-attention/24',
    '/runs': 'bg-section-runs/24',
    '/tickets': 'bg-section-tickets/24',
    '/tasks': 'bg-section-tasks/24',
    '/pull-requests': 'bg-section-pull-requests/24',
    '/chores': 'bg-section-chores/24',
    '/reports': 'bg-section-reports/24',
    '/memory': 'bg-section-memory/24',
    '/settings': 'bg-section-settings/24',
}

/** Each section's color as a solid fill: the bar down the nav highlight's left edge. */
export const SECTION_FILL: Record<Section, string> = {
    '/attention': 'bg-section-attention',
    '/runs': 'bg-section-runs',
    '/tickets': 'bg-section-tickets',
    '/tasks': 'bg-section-tasks',
    '/pull-requests': 'bg-section-pull-requests',
    '/chores': 'bg-section-chores',
    '/reports': 'bg-section-reports',
    '/memory': 'bg-section-memory',
    '/settings': 'bg-section-settings',
}
