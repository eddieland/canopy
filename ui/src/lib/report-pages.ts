// The pages under Reports, as the nav lists them and the reports page's cards open them: one name and one hint each.

/** A page under Reports: where it is, its name, and what it holds, the nav's tooltip and its card's on the home. */
export interface ReportPage {
    /** Its route. */
    to:
        | '/reports/spend'
        | '/reports/checklist'
        | '/reports/health'
        | '/reports/ci'
        | '/reports/reviews'
        | '/reports/plans'
    /** Its name. */
    label: string
    /** What it holds, for an operator who does not know it yet. */
    hint: string
}

/** The pages under Reports, in the nav's order. */
export const REPORT_PAGES = [
    {
        to: '/reports/spend',
        label: 'Spend',
        hint: 'What agent runs cost over the last 24 hours, 7 days, or 30 days',
    },
    {
        to: '/reports/checklist',
        label: 'Checklist',
        hint: "How workers answered each repository's checklist, item by item, over the last days",
    },
    {
        to: '/reports/health',
        label: 'Health',
        hint: "How the last days' runs ended, the newest failures, and what the guards refused",
    },
    {
        to: '/reports/ci',
        label: 'CI',
        hint: 'Which checks fail, what fixing them cost, and whether flaky kicks worked',
    },
    {
        to: '/reports/reviews',
        label: 'Reviews',
        hint: "Who reviews, how soon first reviews come, the feedback rounds, and canopy's reviewer",
    },
    {
        to: '/reports/plans',
        label: 'Plans',
        hint: 'How plans were approved, by the planner or by you, and whether their PRs needed a resume',
    },
] as const satisfies readonly ReportPage[]
