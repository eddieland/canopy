import type { SeasonId } from '@/lib/seasons'

/**
 * What stands beside Sprig in a season (src/lib/seasons.ts), on the same floor as its keyboard, over a soft shadow: a
 * carved jack-o'-lantern whose candle flickers, a gift with a bow, a glossy heart with a smaller one behind, or a
 * veined shamrock. Decoration only, hidden from a screen reader.
 */
export function SeasonDecoration({ id, className }: { id: SeasonId; className?: string }) {
    return (
        <svg viewBox="0 0 28 26" className={className} aria-hidden data-testid="buddy-season" data-season={id}>
            <ellipse cx="14" cy="25" rx="10" ry="1" className="fill-buddy-pupil opacity-15" />
            {DRAWINGS[id]}
        </svg>
    )
}

/** The jack-o'-lantern's carved face: eyes, nose, and a mouth, drawn twice, as the cut wall and the glow inside. */
const FACE = [
    'M7.8 13.6 L11.6 13.6 L10.2 10.2 Z',
    'M16.4 13.6 L20.2 13.6 L17.8 10.2 Z',
    'M13 15.7 L15 15.7 L14 14.1 Z',
    'M7.6 17.2 Q14 19.4 20.4 17.2 Q19 22.6 14 22.8 Q9 22.6 7.6 17.2 Z',
].join(' ')

/** A shamrock's leaflet, pointing up from where the three meet. */
const LEAFLET = 'M14 15 C9 13 8 7 11 6 C13 5.5 14 7 14 8 C14 7 15 5.5 17 6 C20 7 19 13 14 15 Z'
/** The right half of a leaflet, which the light misses. */
const LEAFLET_SHADE = 'M14 15 C19 13 20 7 17 6 C15 5.5 14 7 14 8 Z'

/** A heart, the size of the drawing. */
const HEART = 'M14 24 C6 18 3 14 3 10 A5.5 5.5 0 0 1 14 7.5 A5.5 5.5 0 0 1 25 10 C25 14 22 18 14 24 Z'

/** A four-pointed twinkle of light, centered on 0 0, a unit across each way. */
const TWINKLE = 'M0 -1 Q0.15 -0.15 1 0 Q0.15 0.15 0 1 Q-0.15 0.15 -1 0 Q-0.15 -0.15 0 -1 Z'

const DRAWINGS: Record<SeasonId, React.JSX.Element> = {
    halloween: (
        <>
            {/* The stem, a curl of vine, and a leaf. */}
            <path
                d="M15.6 2.4 C18 1.3 19.6 3 18.6 4.2 C17.9 5 16.9 4.3 17.5 3.6"
                fill="none"
                strokeWidth="0.6"
                strokeLinecap="round"
                className="stroke-buddy-leaf"
            />
            <path d="M15.2 6.8 C17 4.8 20.4 5 21.6 6.4 C19.6 8 17.2 8 15.2 6.8 Z" className="fill-buddy-leaf" />
            <path
                d="M15.6 6.8 C17.6 6.4 19.4 6.3 21 6.4"
                fill="none"
                strokeWidth="0.4"
                className="stroke-buddy-leaf-shade"
            />
            <path
                d="M12.6 8 C12.4 5.4 13.3 3.2 15.6 1.8 L16.7 3 C15 4.2 14.6 5.8 15.2 8 Z"
                className="fill-buddy-leaf-shade"
            />
            {/* The body, five ribs: the outer two turned away into shade. */}
            <ellipse cx="8" cy="16.3" rx="6.6" ry="8.2" className="fill-buddy-ghost-pumpkin-shade" />
            <ellipse cx="20" cy="16.3" rx="6.6" ry="8.2" className="fill-buddy-ghost-pumpkin-shade" />
            <g strokeWidth="0.5" className="fill-buddy-ghost-pumpkin stroke-buddy-ghost-pumpkin-shade">
                <ellipse cx="10.6" cy="16" rx="6" ry="8.8" />
                <ellipse cx="17.4" cy="16" rx="6" ry="8.8" />
                <ellipse cx="14" cy="15.8" rx="5" ry="9.2" />
            </g>
            <path
                d="M10.4 11.2 Q11.2 8.4 13.6 7.4"
                fill="none"
                strokeWidth="0.9"
                strokeLinecap="round"
                className="stroke-buddy-eye opacity-50"
            />
            {/* The face: the cut wall, then the candlelight inside, set down and in so the wall shows above it. */}
            <path d={FACE} className="fill-buddy-ghost-pumpkin-shade" />
            <g className="animate-buddy-candle">
                <path d={FACE} transform="translate(0.3 0.45)" className="fill-buddy-hat-gold" />
                <ellipse cx="14" cy="20.4" rx="2.2" ry="0.8" className="fill-buddy-hat-cloth opacity-40" />
            </g>
            <g className="fill-buddy-ghost-pumpkin">
                <path d="M10.5 17.6 L12.2 17.9 L11.9 19.7 L10.8 19.5 Z" />
                <path d="M17.5 17.6 L15.8 17.9 L16.1 19.7 L17.2 19.5 Z" />
                <path d="M13 23 L13.4 21.2 L14.6 21.2 L15 23 Z" />
            </g>
        </>
    ),
    winter: (
        <>
            {/* The box, in snowflake paper, under its lid's shadow. */}
            <rect x="4.5" y="11.5" width="19" height="13" rx="1" className="fill-buddy-hat-band" />
            <g className="fill-buddy-hat-cloth opacity-60">
                <circle cx="7.4" cy="16" r="0.7" />
                <circle cx="10.2" cy="21.4" r="0.7" />
                <circle cx="18.2" cy="15.6" r="0.7" />
                <circle cx="21" cy="21" r="0.7" />
                <circle cx="7.6" cy="22.6" r="0.4" />
                <circle cx="20.6" cy="18" r="0.4" />
            </g>
            <path d={TWINKLE} transform="translate(9.6 18.2) scale(1.3)" className="fill-buddy-hat-cloth opacity-60" />
            <path d={TWINKLE} transform="translate(18.6 22.2) scale(1.1)" className="fill-buddy-hat-cloth opacity-60" />
            <rect x="12.6" y="11.5" width="2.8" height="13" className="fill-buddy-hat-gold" />
            <rect x="4.5" y="12.5" width="19" height="1.2" className="fill-buddy-pupil opacity-20" />
            {/* The lid, a little wider than the box, with the ribbon over it. */}
            <rect x="3.5" y="9" width="21" height="3.6" rx="0.8" className="fill-buddy-hat-band" />
            <rect x="4.3" y="9.5" width="19.4" height="0.6" rx="0.3" className="fill-buddy-eye opacity-30" />
            <rect x="12.6" y="9" width="2.8" height="3.6" className="fill-buddy-hat-gold" />
            <rect x="12.6" y="11.6" width="2.8" height="1" className="fill-buddy-ghost-gilt-shade" />
            {/* The bow: two tails, two loops with their insides in shade, and the knot. */}
            <g strokeWidth="0.35" strokeLinejoin="round" className="fill-buddy-hat-gold stroke-buddy-ghost-gilt-shade">
                <path d="M13.2 9.2 L9.4 14 L10.9 13.8 L11.2 15.2 L14.4 9.8 Z" />
                <path d="M14.8 9.2 L18.6 14 L17.1 13.8 L16.8 15.2 L13.6 9.8 Z" />
            </g>
            <g className="fill-buddy-hat-gold">
                <path d="M14 9 C11 3.6 5.2 4.6 6.4 7.4 C7.2 9.2 11 9.4 14 9 Z" />
                <path d="M14 9 C17 3.6 22.8 4.6 21.6 7.4 C20.8 9.2 17 9.4 14 9 Z" />
            </g>
            <g className="fill-buddy-ghost-gilt-shade">
                <path d="M12.9 8.6 C11 5.8 8.1 5.9 8.2 7.2 C8.4 8.3 10.9 8.7 12.9 8.6 Z" />
                <path d="M15.1 8.6 C17 5.8 19.9 5.9 19.8 7.2 C19.6 8.3 17.1 8.7 15.1 8.6 Z" />
            </g>
            <ellipse
                cx="14"
                cy="8.9"
                rx="1.6"
                ry="1.3"
                strokeWidth="0.4"
                className="fill-buddy-hat-gold stroke-buddy-ghost-gilt-shade"
            />
        </>
    ),
    valentines: (
        <>
            {/* A smaller heart behind, tipped over its shoulder. */}
            <path
                d={HEART}
                transform="translate(22.6 6.4) rotate(18) scale(0.4) translate(-14 -14)"
                className="fill-buddy-hat-band"
            />
            <g transform="translate(-1.5 1)">
                <path d={HEART} className="fill-flair-red" />
                <path
                    d="M14 24 C22 18 25 14 25 10 A5.5 5.5 0 0 0 23.4 6.1 C24.4 10.6 21.6 15.8 14 24 Z"
                    className="fill-buddy-pupil opacity-20"
                />
                <ellipse
                    cx="8.2"
                    cy="9.6"
                    rx="2.2"
                    ry="1.2"
                    transform="rotate(-38 8.2 9.6)"
                    className="fill-buddy-eye opacity-60"
                />
                <circle cx="6.2" cy="12.6" r="0.55" className="fill-buddy-eye opacity-60" />
            </g>
            <path d={TWINKLE} transform="translate(3 3) scale(2)" className="fill-buddy-hat-gold" />
        </>
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
                <g key={turn} transform={`rotate(${turn} 14 15)`}>
                    <path d={LEAFLET} strokeWidth="0.5" className="fill-buddy-leaf stroke-buddy-leaf-shade" />
                    <path d={LEAFLET_SHADE} className="fill-buddy-leaf-shade opacity-40" />
                    <path
                        d="M14 14.4 L14 8.6"
                        strokeWidth="0.45"
                        strokeLinecap="round"
                        className="stroke-buddy-leaf-shade"
                    />
                    <path
                        d="M10.4 8.4 Q10.8 6.8 12 6.6"
                        fill="none"
                        strokeWidth="0.6"
                        strokeLinecap="round"
                        className="stroke-buddy-eye opacity-40"
                    />
                </g>
            ))}
            <circle cx="14" cy="15" r="0.9" className="fill-buddy-leaf-shade" />
            <path d={TWINKLE} transform="translate(23.6 3.4) scale(1.8)" className="fill-buddy-hat-gold" />
        </>
    ),
}
