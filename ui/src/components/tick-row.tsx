import type { Tick } from '@/api/types'
import { Age } from '@/components/age'
import { Cost } from '@/components/cost'
import { RichText, SUMMARY_LINES } from '@/components/rich-text'
import { ListRow } from '@/components/rows'
import { Chip, RunDot, Word } from '@/components/status'
import { TickLink } from '@/components/tick-link'
import { rowLineFrom } from '@/lib/rows'
import { TICK_TONE, tickState } from '@/lib/ticks'
import { RUN_TOKENS_TITLE, tokensCell } from '@/lib/transcript'
import { cn } from '@/lib/utils'

/**
 * A tick in a list, as `canopy decisions` heads it: its status, its link, whether it was a dry run, decisions, its
 * overseer's cost, tokens, and peak context, and when; its summary under, from its id, as a run's is on its subject's
 * page.
 */
export function TickRow({ tick }: { tick: Tick }) {
    return (
        <ListRow kind="tick" data-testid={`tick-${tick.id}`}>
            <span
                className={cn(
                    'flex min-w-0 items-center gap-1.5 font-mono text-xs',
                    TICK_TONE[tick.status] ?? 'text-muted-foreground',
                )}
            >
                <RunDot state={tickState(tick.status)} />
                <Word word={tick.status} className="truncate" />
            </span>
            <TickLink id={tick.id} />
            <span className="flex">{tick.dry_run && <Chip>dry run</Chip>}</span>
            <span className="readout text-right text-xs text-muted-foreground" data-testid="tick-decisions">
                {tick.decisions === 1 ? '1 decision' : `${tick.decisions} decisions`}
            </span>
            <Cost usd={tick.cost_usd} className="text-right text-xs text-muted-foreground" />
            <TokensCell n={tick.new_tokens} counts="tokens" />
            <TokensCell n={tick.peak_context} counts="peak" />
            <Age variant="span" started={tick.started_at} ended={tick.ended_at} className="text-right" />
            {tick.summary && <RichText text={tick.summary} lines={SUMMARY_LINES} className={rowLineFrom('id')} />}
        </ListRow>
    )
}

function TokensCell({ n, counts }: { n: number | null; counts: string }) {
    return (
        <span
            className="readout text-right text-xs text-muted-foreground"
            title={n === null ? 'none reported' : RUN_TOKENS_TITLE}
            data-testid={`tick-${counts}`}
        >
            {tokensCell(n, counts)}
        </span>
    )
}
