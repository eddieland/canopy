import { useMatchRoute } from '@tanstack/react-router'

import { SECTIONS } from '@/lib/sections'
import type { Section } from '@/lib/sections'

/**
 * The section the current page belongs to, matched as the nav matches it (a ticket's page is in Tickets, a chore's in
 * Chores, a tick's in Ticks); undefined on a page in none, such as the 404.
 */
export function useSection(): Section | undefined {
    const matchRoute = useMatchRoute()
    return SECTIONS.find((to) => matchRoute({ to, fuzzy: true }) !== false)
}
