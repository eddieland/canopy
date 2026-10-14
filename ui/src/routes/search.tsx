import { useQuery } from '@tanstack/react-query'
import { createFileRoute } from '@tanstack/react-router'

import { searchQuery } from '@/api/queries'
import type { SearchHit, SearchSource } from '@/api/types'
import { Age } from '@/components/age'
import { ChoreLink } from '@/components/chore-link'
import { Empty, PageHeader, Panel, PanelHeader, PanelSkeleton } from '@/components/panel'
import { ListRow } from '@/components/rows'
import { RunLink } from '@/components/run-link'
import { MarkedText } from '@/components/marked-text'
import { Chip } from '@/components/status'
import { TickLink } from '@/components/tick-link'
import { TicketLink } from '@/components/ticket-link'
import { bySource, SEARCH_MIN, searchQueryOf, SOURCE_LABEL } from '@/lib/search'
import { cn } from '@/lib/utils'

interface SearchParams {
    q?: string | undefined
}

/** Search across the journal, with the query kept in `?q=`. */
export const Route = createFileRoute('/search')({
    // Typed search params: a query the server would refuse is dropped, so the page asks for one instead.
    validateSearch: (search: Record<string, unknown>): SearchParams => ({ q: searchQueryOf(search['q']) }),
    component: SearchPage,
})

function SearchPage() {
    const { q } = Route.useSearch()
    return (
        <>
            <PageHeader
                root="Search"
                title={q === undefined ? 'Search' : `“${q}”`}
                tab={q === undefined ? 'Search' : `Search “${q}”`}
            >
                Tickets by key and branch, every conversation, chore runs, decisions, and ticks that hold every word,
                newest first. Not searched: transcripts, ticket titles (a branch carries its words), and reviews.
            </PageHeader>
            {q === undefined ? (
                <Panel>
                    <Empty size="panel">
                        no search yet: type at least {SEARCH_MIN} characters in the search box, or press /
                    </Empty>
                </Panel>
            ) : (
                <Results q={q} />
            )}
        </>
    )
}

function Results({ q }: { q: string }) {
    const { data, isPlaceholderData } = useQuery(searchQuery(q))
    if (data === undefined) {
        return (
            <Panel>
                <PanelSkeleton className="min-h-72" />
            </Panel>
        )
    }
    const groups = bySource(data.hits)
    if (groups.length === 0) {
        return (
            <Panel>
                <Empty size="panel">nothing in the journal holds every word</Empty>
            </Panel>
        )
    }
    return (
        // The previous query's hits stay while the next one's load, dimmed so they do not read as its answer.
        <div
            className={cn('flex flex-col gap-6 transition-opacity', isPlaceholderData && 'opacity-60')}
            data-testid="search-results"
        >
            {groups.map(([source, hits]) => (
                <Panel key={source} data-testid={`search-${source}`}>
                    <PanelHeader label={SOURCE_LABEL[source]}>
                        <span className="readout text-xs text-muted-foreground">
                            {data.more.includes(source) ? `newest ${hits.length}` : hits.length}
                        </span>
                    </PanelHeader>
                    <ul className="divide-y">
                        {hits.map((hit) => (
                            <Row key={rowKey(hit)} hit={hit} words={data.words} />
                        ))}
                    </ul>
                </Panel>
            ))}
        </div>
    )
}

function rowKey(hit: SearchHit) {
    return [hit.source, hit.ticket_key, hit.chore, hit.run_id, hit.tick_id, hit.at, hit.snippet].join('|')
}

function Row({ hit, words }: { hit: SearchHit; words: string[] }) {
    return (
        <ListRow kind="search-hit" className="items-baseline" data-testid="search-hit">
            <span className="flex min-w-0 flex-col gap-0.5">
                <Where hit={hit} />
            </span>
            <span className="flex min-w-0">
                {hit.label !== null && <Chip className="min-w-0 shrink" word={hit.label} />}
            </span>
            {/* Text, never markup; its URLs are not linked, since a snippet may cut one short. */}
            <p className="text-sm break-words">
                <MarkedText text={hit.snippet} words={words} />
            </p>
            <Age at={hit.at} variant="ago" className="text-right" />
        </ListRow>
    )
}

const SUBJECT_FIRST: ReadonlySet<SearchSource> = new Set(['ticket', 'message', 'chore_run'])

/** Where a hit opens: its ticket or chore, then the run that said it or the tick that decided it. */
function Where({ hit }: { hit: SearchHit }) {
    const subject =
        hit.ticket_key === null ? (
            hit.chore === null ? null : (
                <ChoreLink name={hit.chore} />
            )
        ) : (
            <TicketLink ticketKey={hit.ticket_key} />
        )
    const tick = hit.tick_id === null ? null : <TickLink id={hit.tick_id} />
    // A chore run has no `run:ID` page (DESIGN §22): its chore's page lists it.
    const run = hit.run_id !== null && hit.source === 'message' ? <RunLink id={hit.run_id} /> : null
    if (SUBJECT_FIRST.has(hit.source)) {
        return (
            <>
                {subject}
                {run}
            </>
        )
    }
    return (
        <>
            {tick}
            {subject}
        </>
    )
}
