import type { SeasonId } from '@/lib/seasons'

/**
 * What stands beside Sprig in a season (src/lib/seasons.ts), on the same floor as its keyboard: a jack-o'-lantern
 * whose candle flickers, a gift, a heart, or a shamrock. Decoration only, hidden from a screen reader.
 */
export function SeasonDecoration({ id, className }: { id: SeasonId; className?: string }) {
    return (
        <svg viewBox="0 0 28 26" className={className} aria-hidden data-testid="buddy-season" data-season={id}>
            {DRAWINGS[id]}
        </svg>
    )
}

const DRAWINGS: Record<SeasonId, React.JSX.Element> = {
    halloween: (
        <>
            <path d="M13 7 C13 4 14 2 16.5 1 L17.5 2.5 C15.5 3.5 15 5 15.2 7 Z" className="fill-buddy-leaf-shade" />
            <ellipse cx="8.5" cy="16" rx="7.5" ry="9" className="fill-buddy-ghost-pumpkin-shade" />
            <ellipse cx="19.5" cy="16" rx="7.5" ry="9" className="fill-buddy-ghost-pumpkin-shade" />
            <ellipse cx="14" cy="16" rx="7" ry="9.8" className="fill-buddy-ghost-pumpkin" />
            <g
                strokeWidth="0.9"
                strokeLinejoin="round"
                className="animate-buddy-candle fill-buddy-hat-gold stroke-buddy-ghost-pumpkin-shade"
            >
                <path d="M6.5 13.5 L11 13.5 L8.8 9.5 Z" />
                <path d="M17 13.5 L21.5 13.5 L19.2 9.5 Z" />
                <path d="M12.8 16 L15.2 16 L14 14 Z" />
                <path
                    d={[
                        'M6.5 17.5 L8.5 18.6 L10 17.6 L11.8 18.9 L14 17.8 L16.2 18.9 L18 17.6 L19.5 18.6 L21.5 17.5',
                        'Q19.5 23 14 23 Q8.5 23 6.5 17.5 Z',
                    ].join(' ')}
                />
            </g>
        </>
    ),
    winter: (
        <>
            <rect x="4" y="10" width="20" height="15" rx="1" className="fill-buddy-hat-band" />
            <rect x="12.5" y="10" width="3" height="15" className="fill-buddy-hat-gold" />
            <path d="M14 10 C10 3 5 6 9 9 Z M14 10 C18 3 23 6 19 9 Z" className="fill-buddy-hat-gold" />
        </>
    ),
    valentines: (
        <path
            d="M14 24 C6 18 3 14 3 10 A5.5 5.5 0 0 1 14 7.5 A5.5 5.5 0 0 1 25 10 C25 14 22 18 14 24 Z"
            className="fill-flair-red"
        />
    ),
    shamrock: (
        <>
            <path
                d="M14 15 C14 19 15 22 18 25"
                fill="none"
                strokeWidth="1.5"
                strokeLinecap="round"
                className="stroke-buddy-leaf-shade"
            />
            {[-90, 0, 90].map((turn) => (
                <path
                    key={turn}
                    d="M14 15 C9 13 8 7 11 6 C13 5.5 14 7 14 8 C14 7 15 5.5 17 6 C20 7 19 13 14 15 Z"
                    transform={`rotate(${turn} 14 15)`}
                    className="fill-buddy-leaf"
                />
            ))}
        </>
    ),
}
