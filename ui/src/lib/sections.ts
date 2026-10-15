// The side nav's sections, each with a color of its own (ui/DESIGN.md, "Tokens"). A section's color is identity,
// never state: it marks the nav's icons, its highlight, and the trail over each page, and nothing in the data.

/** Every section, by its path, in the nav's order. */
export const SECTIONS = [
    '/attention',
    '/runs',
    '/worktrees',
    '/tickets',
    '/pull-requests',
    '/reviews',
    '/chores',
    '/ticks',
    '/spend',
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
    '/pull-requests': 'Pull requests',
    '/reviews': 'Reviews',
    '/chores': 'Chores',
    '/ticks': 'Ticks',
    '/spend': 'Spend',
    '/settings': 'Settings',
}

// Full class names, written out, so Tailwind finds them. One entry per section; the types make a missing one an error.

/** Each section's color as text: its icon and the label over its pages. */
export const SECTION_TEXT: Record<Section, string> = {
    '/attention': 'text-section-attention',
    '/runs': 'text-section-runs',
    '/worktrees': 'text-section-worktrees',
    '/tickets': 'text-section-tickets',
    '/pull-requests': 'text-section-pull-requests',
    '/reviews': 'text-section-reviews',
    '/chores': 'text-section-chores',
    '/ticks': 'text-section-ticks',
    '/spend': 'text-section-spend',
    '/settings': 'text-section-settings',
}

/** Each section's color as a faint background: the nav's highlight on the section shown. */
export const SECTION_TINT: Record<Section, string> = {
    '/attention': 'bg-section-attention/16',
    '/runs': 'bg-section-runs/16',
    '/worktrees': 'bg-section-worktrees/16',
    '/tickets': 'bg-section-tickets/16',
    '/pull-requests': 'bg-section-pull-requests/16',
    '/reviews': 'bg-section-reviews/16',
    '/chores': 'bg-section-chores/16',
    '/ticks': 'bg-section-ticks/16',
    '/spend': 'bg-section-spend/16',
    '/settings': 'bg-section-settings/16',
}

/** Each section's color as a solid fill: the bar at the nav highlight's left edge. */
export const SECTION_FILL: Record<Section, string> = {
    '/attention': 'bg-section-attention',
    '/runs': 'bg-section-runs',
    '/worktrees': 'bg-section-worktrees',
    '/tickets': 'bg-section-tickets',
    '/pull-requests': 'bg-section-pull-requests',
    '/reviews': 'bg-section-reviews',
    '/chores': 'bg-section-chores',
    '/ticks': 'bg-section-ticks',
    '/spend': 'bg-section-spend',
    '/settings': 'bg-section-settings',
}
