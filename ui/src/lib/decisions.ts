/** How a decision's action is shown (DESIGN.md): a refusal in the failure color, an attention item in the color of what
 * waits on the operator, anything else plain. */
export type ActionTone = 'refused' | 'attention' | 'other'

export function actionTone(action: string): ActionTone {
    if (action.startsWith('refused:')) return 'refused'
    if (action.startsWith('attention:')) return 'attention'
    return 'other'
}
