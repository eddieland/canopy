import { Link } from '@tanstack/react-router'

import type { PlanCheck, PlanCheckFile } from '@/api/types'
import { Empty, Panel, PanelHeader } from '@/components/panel'

/** What the panel says when the run's files and the plan's steps agree. */
export const PLAN_FOLLOWED =
    'Every file it touched is named by a step, and every step that names a file had one touched.'

/**
 * An `implement`'s files held to the steps of the approved plan it followed (DESIGN §25, §45), under its Diff panels:
 * the files it touched that no step names, then the steps that name files none of which it touched. canopy holds them
 * in code, a step naming a file in a code span, so it is a reading, not a verdict; a step that names no file is never
 * listed. Why they could not be held, when they could not. Nothing for any other run.
 */
export function PlanCheckPanel({ check, ticketKey }: { check: PlanCheck | null; ticketKey: string }) {
    if (check === null) {
        return null
    }
    return (
        <Panel data-testid="plan-check">
            <PanelHeader label="Against the plan">
                <Link
                    to="/tickets/$key/plan"
                    params={{ key: ticketKey }}
                    title="The ticket's plans, the one this run followed among them"
                    className="font-mono text-xs text-accent underline-offset-4 hover:underline"
                >
                    plan {check.plan_id}
                </Link>
            </PanelHeader>
            <PlanCheckBody check={check} />
        </Panel>
    )
}

/** The panel's rows: why nothing was held, that nothing stands out, or the two lists. */
function PlanCheckBody({ check }: { check: PlanCheck }) {
    if (check.unchecked !== null) {
        return <Empty>Not held to the plan: {check.unchecked}</Empty>
    }
    if (check.unnamed.length === 0 && check.untouched.length === 0) {
        return <Empty>{PLAN_FOLLOWED}</Empty>
    }
    return (
        <div className="flex flex-col py-1.5">
            {check.unnamed.length > 0 && (
                <section aria-label="Touched, named by no step">
                    <h3 className="px-3 pt-1 text-xs text-muted-foreground">Touched, named by no step</h3>
                    <ul className="flex flex-col py-1">
                        {check.unnamed.map((file) => (
                            <UnnamedFile key={`${file.repo}:${file.path}`} file={file} />
                        ))}
                    </ul>
                </section>
            )}
            {check.untouched.length > 0 && (
                <section aria-label="Steps none of whose files it touched">
                    <h3 className="px-3 pt-1 text-xs text-muted-foreground">Steps none of whose files it touched</h3>
                    <ul className="flex flex-col py-1">
                        {check.untouched.map((step) => (
                            <li key={`${step.number}:${step.title}`} className="px-3 py-0.5 text-sm">
                                Step {step.number}: {step.title}
                            </li>
                        ))}
                    </ul>
                </section>
            )}
        </div>
    )
}

/** A file no step names: its repository, then its path, cut from the left so its name shows. */
function UnnamedFile({ file }: { file: PlanCheckFile }) {
    return (
        <li className="flex items-baseline gap-3 px-3 py-0.5 font-mono text-xs">
            <span className="shrink-0 text-muted-foreground">{file.repo}</span>
            <span className="min-w-0 truncate [direction:rtl]" title={file.path}>
                {/* The marks keep a path that starts or ends in punctuation reading left to right. */}
                <bdi>{file.path}</bdi>
            </span>
        </li>
    )
}
