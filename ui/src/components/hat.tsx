import type { HatId } from '@/lib/hats'

/**
 * Sprig's hats, drawn in Sprig's own units (`Figure` in src/components/shell/buddy.tsx): the brim sits on the top of
 * the wire, around y 13, and the leaf, drawn first, shows behind the crown like a feather. Each is a group to place in
 * Sprig's drawing, or `HatPreview` for the shop.
 */
export function HatDrawing({ id }: { id: HatId }) {
    return <g data-hat={id}>{DRAWINGS[id]}</g>
}

/** One hat on its own, for the shop in Settings. */
export function HatPreview({ id, className }: { id: HatId; className?: string }) {
    return (
        <svg viewBox="8 -12 32 30" className={className} aria-hidden>
            <HatDrawing id={id} />
        </svg>
    )
}

// The outline cloth gets, so a white hat shows on a white page.
const CLOTH = 'fill-buddy-hat-cloth stroke-muted-foreground'

const DRAWINGS: Record<HatId, React.JSX.Element> = {
    party: (
        <>
            <path d="M15 14 L33 14 L22 -5 Z" className="fill-buddy-hat-blue" />
            <path d="M17.5 9.5 L30.5 9.5 L29.3 7.5 L18.7 7.5 Z" className="fill-buddy-hat-gold" />
            <path d="M20.2 3 L24.8 3 L23.9 1.3 L21.1 1.3 Z" className="fill-buddy-hat-gold" />
            <circle cx="22" cy="-5" r="2.4" className="fill-buddy-hat-band" />
        </>
    ),
    beanie: (
        <>
            <path d="M12.5 13 A11.5 10.5 0 0 1 35.5 13 Z" className="fill-buddy-hat-band" />
            <rect x="11.5" y="11" width="25" height="5" rx="1.5" className="fill-buddy-hat" />
            <circle cx="24" cy="2" r="3" strokeWidth="0.6" className={CLOTH} />
        </>
    ),
    propeller: (
        <>
            <path d="M13 14 A11 10 0 0 1 35 14 Z" className="fill-buddy-hat-blue" />
            <path d="M24 4 A11 10 0 0 1 35 14 L24 14 Z" className="fill-buddy-hat-band" />
            <path d="M33 13.5 Q39 12.5 42 14.5 Q37 16 33 15.2 Z" className="fill-buddy-hat-blue" />
            <path d="M24 4 V0" strokeWidth="1.2" strokeLinecap="round" className="stroke-buddy-hat" />
            <g className="animate-buddy-propeller">
                <ellipse cx="19.5" cy="0" rx="4.5" ry="1.3" className="fill-buddy-hat-gold" />
                <ellipse cx="28.5" cy="0" rx="4.5" ry="1.3" className="fill-buddy-hat-band" />
            </g>
            <circle cx="24" cy="0" r="1.1" className="fill-buddy-hat" />
        </>
    ),
    top: (
        <>
            <rect x="16.5" y="-4" width="15" height="17.5" rx="1" className="fill-buddy-hat" />
            <rect x="16.5" y="8" width="15" height="3" className="fill-buddy-hat-band" />
            <ellipse cx="24" cy="13.5" rx="13" ry="2.2" className="fill-buddy-hat" />
        </>
    ),
    toque: (
        <>
            <circle cx="24" cy="-0.5" r="6" strokeWidth="0.6" className={CLOTH} />
            <circle cx="17.5" cy="3.5" r="5" strokeWidth="0.6" className={CLOTH} />
            <circle cx="30.5" cy="3.5" r="5" strokeWidth="0.6" className={CLOTH} />
            <rect x="16" y="6" width="16" height="8" rx="1" strokeWidth="0.6" className={CLOTH} />
        </>
    ),
    wizard: (
        <>
            <path d="M14 13 C20 6 22 -2 28 -9 C26 -2 29 6 34 13 Z" className="fill-buddy-hat-blue" />
            <ellipse cx="24" cy="13.5" rx="14" ry="2" className="fill-buddy-hat-blue" />
            <path d={star(21.5, 7, 2)} className="fill-buddy-hat-gold" />
            <path d={star(27, 1.5, 1.5)} className="fill-buddy-hat-gold" />
            <path d={star(25.5, 10, 1.2)} className="fill-buddy-hat-gold" />
        </>
    ),
    crown: (
        <>
            <path d="M14 14 V4 L19 9 L24 1 L29 9 L34 4 V14 Z" className="fill-buddy-hat-gold" />
            {[14, 24, 34].map((x) => (
                <circle key={x} cx={x} cy={x === 24 ? 1 : 4} r="1.3" className="fill-buddy-hat-gold" />
            ))}
            <circle cx="24" cy="11" r="1.6" className="fill-buddy-hat-band" />
            <circle cx="18.5" cy="11.2" r="1.1" className="fill-buddy-hat-blue" />
            <circle cx="29.5" cy="11.2" r="1.1" className="fill-buddy-hat-blue" />
        </>
    ),
    halo: <ellipse cx="24" cy="2" rx="12" ry="3" fill="none" strokeWidth="2.2" className="stroke-buddy-hat-gold" />,
}

/** A four-pointed sparkle centered on (x, y), `r` from its center to each point. */
function star(x: number, y: number, r: number): string {
    const w = r * 0.3
    const points = [
        [x, y - r],
        [x + w, y - w],
        [x + r, y],
        [x + w, y + w],
        [x, y + r],
        [x - w, y + w],
        [x - r, y],
        [x - w, y - w],
    ]
    return `M${points.map(([px, py]) => `${px} ${py}`).join(' L')} Z`
}
