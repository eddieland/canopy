import { useQuery } from '@tanstack/react-query'
import { createFileRoute } from '@tanstack/react-router'

import { searchQuery } from '@/api/queries'
import type { SearchHit, SearchSource } from '@/api/types'
import { Age } from '@/components/age'
import { ChoreLink } from '@/components/chore-link'
import { PageHeader, Panel, PanelHeader, Placeholder } from '@/components/panel'
import { RunLink } from '@/components/run-link'
import { Chip } from '@/components/status'
import { TickLink } from '@/components/tick-link'
import { TicketLink } from '@/components/ticket-link'
import { Skeleton } from '@/components/ui/skeleton'
import { bySource, marked, SEARCH_MIN, searchQueryOf, SOURCE_LABEL } from '@/lib/search'
import { cn } from '@/lib/utils'

interface SearchParams {
    q?: string | undefined
}

export const Route = createFileRoute('/search')({
    // Typed search params: a query the server would refuse is dropped, so the page asks for one instead.
    validateSearch: (search: Record<string, unknown>): SearchParams => ({ q: searchQueryOf(search['q']) }),
    component: SearchPage,
})

function SearchPage() {
    const { q } = Route.useSearch()
    return (
        <>
            <PageHeader label="Search" title={q === undefined ? 'Search' : `“${q}”`}>
                Tickets by key and branch, every conversation, chore runs, decisions, and ticks that hold every word,
                newest first. Not searched: transcripts, ticket titles (a branch carries its words), and reviews.
            </PageHeader>
            {q === undefined ? (
                <Panel>
                    <Placeholder>type at least {SEARCH_MIN} characters in the search box, or press /</Placeholder>
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
                <div className="flex min-h-72 flex-col gap-2 p-3">
                    <Skeleton className="h-4 w-2/3" />
                    <Skeleton className="h-4 w-1/2" />
                </div>
            </Panel>
        )
    }
    const groups = bySource(data.hits)
    if (groups.length === 0) {
        return (
            <Panel>
                <Placeholder>nothing in the journal holds every word</Placeholder>
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
        <li className="flex items-baseline gap-3 px-3 py-2.5" data-testid="search-hit">
            <span className="flex w-36 shrink-0 flex-col gap-0.5">
                <Where hit={hit} />
            </span>
            {hit.label !== null && <Chip className="w-32 justify-center truncate" word={hit.label} />}
            {/* Text, never markup; its URLs are not linked, since a snippet may cut one short. */}
            <p className="min-w-0 flex-1 text-sm break-words">
                {/* A snippet's pieces never reorder, so their index is their key. */}
                {marked(hit.snippet, words).map((piece, i) =>
                    piece.mark ? (
                        <mark key={i} className="rounded-xs bg-accent/20 text-foreground">
                            {piece.text}
                        </mark>
                    ) : (
                        <span key={i}>{piece.text}</span>
                    ),
                )}
            </p>
            <span className="flex w-20 shrink-0 justify-end gap-1 text-xs text-muted-foreground">
                <Age at={hit.at} /> ago
            </span>
        </li>
    )
}

const SUBJECT_FIRST: ReadonlySet<SearchSource> = new Set(['ticket', 'message', 'chore_run'])

/** Where a hit opens: its ticket or chore, then the run that said it or the tick that decided it. */
function Where({ hit }: { hit: SearchHit }) {
    const subject =
        hit.ticket_key !== null ? (
            <TicketLink ticketKey={hit.ticket_key} />
        ) : hit.chore !== null ? (
            <ChoreLink name={hit.chore} />
        ) : null
    const tick = hit.tick_id !== null ? <TickLink id={hit.tick_id} /> : null
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
