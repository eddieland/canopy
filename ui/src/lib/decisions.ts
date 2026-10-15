import type { Tone } from '@/lib/tone'

/**
 * An action's chip tone, from its prefix (DESIGN.md): a refusal (`refused:`) in the failure color, an attention item
 * (`attention:`) in the color of what waits on the operator, anything else plain.
 */
export function actionTone(action: string): Tone {
    if (action.startsWith('refused:')) {
        return 'failed'
    }
    if (action.startsWith('attention:')) {
        return 'blocked'
    }
    return 'plain'
}
