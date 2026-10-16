// A plan as a planner writes one (docs/design/PLANNING.md §25, The prompt), with the operator's comments on it: what
// the plan editor's page shows over mock data (src/routes/plan-editor.tsx), until plans reach a ticket's page (M44).
// Its threads are anchored as the editor anchors them, so each lands on its passage, but for one whose passage the
// planner has since rewritten, which shows as gone, and one the operator resolved.
import type { PlanThread } from '@/lib/plan-threads'

/** The sample plan, for ABC-102 in the mock journal (canopy/serve/mock.py). */
export const SAMPLE_PLAN = `# Export reports as CSV

## What changes

In **web**, the reports page gains an *Export CSV* button. It calls a new route, \`GET /reports/{id}/export.csv\`,
which streams the report's rows as they are read, so a large report never sits whole in memory.

In **api**, \`ReportQuery\` gains an \`iter_rows()\` method beside \`rows()\`, which the route uses.

## Files

| Repository | File | Why |
| --- | --- | --- |
| web | \`app/reports/export.py\` | the new route |
| web | \`app/templates/report.html\` | the button |
| api | \`api/reports/query.py\` | \`iter_rows()\` |

## Tests

- [ ] a report of three rows exports as a header and three lines
- [ ] a report of 100,000 rows exports without loading them all
- [ ] a cell holding a comma or a quote is escaped as RFC 4180 says

## Out of scope

- Excel's own format, which the ticket does not ask for.
- Scheduling exports.

## Risks

> The reports page renders through a template cache. A new button may need the cache cleared on deploy.`

const AT = '2026-10-08T11:40:00Z'

/** The operator's comments on the sample plan. */
export const SAMPLE_THREADS: PlanThread[] = [
    {
        id: 'sample-1',
        anchor: {
            quote: "streams the report's rows as they are read",
            prefix: 'export.csv, which',
            suffix: ', so a large report never sits whole',
        },
        body: 'Does the proxy in front of web buffer responses? If it does, streaming buys nothing.',
        at: AT,
        resolved: false,
        replies: [{ id: 'sample-1-1', body: 'It buffers up to 1 MB. Say so in the plan.', at: '2026-10-08T11:52:00Z' }],
    },
    {
        id: 'sample-2',
        anchor: { quote: 'Scheduling exports.', prefix: 'the ticket does not ask for.', suffix: '' },
        body: 'Keep this out, but name the ticket that will ask for it: ABC-140.',
        at: AT,
        resolved: false,
        replies: [],
    },
    {
        id: 'sample-3',
        anchor: { quote: 'a header and a row per line', prefix: 'three rows exports as', suffix: '' },
        body: 'Say what the header row holds: the column names as the page shows them, or the field names?',
        at: '2026-10-08T11:20:00Z',
        resolved: false,
        replies: [],
    },
    {
        id: 'sample-4',
        anchor: { quote: 'RFC 4180', prefix: 'quote is escaped as', suffix: 'says' },
        body: 'Good: name the RFC so the worker tests against it.',
        at: '2026-10-08T11:10:00Z',
        resolved: true,
        replies: [],
    },
]
