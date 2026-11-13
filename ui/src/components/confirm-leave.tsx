import {
    AlertDialog,
    AlertDialogAction,
    AlertDialogCancel,
    AlertDialogContent,
    AlertDialogDescription,
    AlertDialogFooter,
    AlertDialogTitle,
} from '@/components/ui/alert-dialog'

/**
 * Asks before the page is left with the operator's words not yet saved or sent, as a document does: Stay, which takes
 * the focus and which Escape gives too, or Leave, which loses them. `lost` says what would go, each part a clause, such
 * as `your edits to the plan are not saved`; the dialog joins them into one sentence.
 */
export function ConfirmLeave({
    open,
    lost,
    onStay,
    onLeave,
}: {
    /** Whether a move away is held, waiting on the answer. */
    open: boolean
    /** What leaving loses, a clause each, in the order they are said. */
    lost: readonly string[]
    /** Called to stay, which drops the held move. */
    onStay: () => void
    /** Called to leave, which lets the held move go on. */
    onLeave: () => void
}) {
    return (
        <AlertDialog
            open={open}
            onOpenChange={(next) => {
                if (!next) {
                    onStay()
                }
            }}
        >
            <AlertDialogContent>
                <AlertDialogTitle>Leave this page?</AlertDialogTitle>
                <AlertDialogDescription>{leaveText(lost)}</AlertDialogDescription>
                <AlertDialogFooter>
                    <AlertDialogCancel>Stay</AlertDialogCancel>
                    <AlertDialogAction onClick={onLeave}>Leave</AlertDialogAction>
                </AlertDialogFooter>
            </AlertDialogContent>
        </AlertDialog>
    )
}

// What leaving loses, as a sentence: `Your edits to the plan are not saved, and what you wrote ... is not sent.`
function leaveText(parts: readonly string[]): string {
    const said = parts.join(', and ')
    return `${said.charAt(0).toUpperCase()}${said.slice(1)}.`
}
