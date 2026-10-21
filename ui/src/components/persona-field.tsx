import { Field } from '@/components/fields'

/** How much of a persona's digest the field shows, as `canopy status` does: enough to tell two versions apart. */
const DIGEST_WIDTH = 12

/**
 * The persona a run or a review wrote in (DESIGN §31): its name, and the start of its text's digest, the whole digest
 * on hover, so two runs in one persona edited between them read apart. Nothing for a run no persona reaches, or one
 * from before canopy recorded it.
 */
export function PersonaField({ persona, digest }: { persona: string | null; digest: string | null }) {
    if (persona === null) {
        return null
    }
    return (
        <Field label="persona" mono>
            {persona}
            {digest !== null && (
                <span className="text-muted-foreground" title={digest}>
                    {' '}
                    {digest.slice(0, DIGEST_WIDTH)}
                </span>
            )}
        </Field>
    )
}
