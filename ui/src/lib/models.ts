import type { ModelsServed, Run } from '@/api/types'

/** What a read of a run's session that failed says, as a reason after `none: `: canopy tries again later. */
export const FAILED_READ = 'its session could not be read, tried again later'

/**
 * The word for a run whose session canopy has not read yet, or could not, so it knows no model that served it: shown
 * muted, why in its tip, never `none`, which would say it ran on nothing.
 */
export const UNREAD = 'unread'

/**
 * What names no model, as the runtime picks its own: shown in muted sans wherever an id would be, never monospace,
 * since it is no id.
 */
export const RUNTIME_DEFAULT = 'runtime default'

/** The model an agent's next run goes to, as a model menu shows it. */
export interface PickerModel {
    /** The model, as `provider/model` or `provider/model@variant`, or null for the runtime's default. */
    model: string | null
    /** The variant `model` names after its id, set apart; null for the model's default. */
    variant: string | null
}

/**
 * A model as `provider/model[@variant]` with its variant set apart, as canopy reads one (`agent_models.parse`): the
 * part after its last `@` when that starts with a letter, since a model's own id may hold a dated `@20250101`.
 */
export function pickerModel(model: string | null): PickerModel {
    if (model === null) {
        return { model, variant: null }
    }
    const at = model.lastIndexOf('@')
    const variant = model.slice(at + 1)
    return at > 0 && /^[A-Za-z][A-Za-z0-9_-]{0,63}$/u.test(variant) ? { model, variant } : { model, variant: null }
}

/**
 * A model at a variant as every page names it, `provider/model@variant`, from config's model and variant apart: the
 * model alone at its default variant, never `at high`.
 */
export function withVariant(model: string, variant: string | null): string {
    return variant === null ? model : `${model}@${variant}`
}

/**
 * Whether a session naming `served` ran on the model canopy `asked` for, as `provider/model[@variant]`: the same id, or
 * `asked` at a variant and `served` the model alone, since a session names a variant only when it is not the model's
 * default, and a run whose variant the runtime no longer lists is refused before it starts.
 */
export function sameModel(asked: string, served: string): boolean {
    if (served === asked) {
        return true
    }
    const at = asked.lastIndexOf('@')
    return at > asked.indexOf('/') && asked.slice(0, at) === served
}

/**
 * Why no model is named as having served a run, by how canopy's last read of its session went (DESIGN §13), why a
 * failed read failed after it in parentheses; null once a model is named.
 */
export function unservedReason(models: ModelsServed): string | null {
    switch (models.status) {
        case 'found': {
            return models.models.length === 0 ? 'its session made no model call' : null
        }
        case 'running': {
            return 'read from its session once it ends'
        }
        case 'unread': {
            return "not read yet: a tick reads a few ended runs' sessions"
        }
        case 'no_session': {
            return 'it reported no session to read'
        }
        case 'missing': {
            return 'the runtime no longer keeps its session'
        }
        case 'failed': {
            return models.error === null ? FAILED_READ : `${FAILED_READ} (${models.error})`
        }
    }
}

/**
 * How a list names each of `ids`, models as `provider/model[@variant]`: without its provider (`claude-opus-4-1`),
 * unless another provider's model in the list has the same name, which keeps its whole id. A list of runs then reads
 * short, and never names two models alike.
 */
export function modelNames(ids: Iterable<string>): ReadonlyMap<string, string> {
    const unique = new Set(ids)
    const named = new Map<string, number>()
    for (const id of unique) {
        const bare = withoutProvider(id)
        named.set(bare, (named.get(bare) ?? 0) + 1)
    }
    return new Map(
        [...unique].map((id) => {
            const bare = withoutProvider(id)
            return [id, named.get(bare) === 1 ? bare : id]
        }),
    )
}

/** Every model a list of `runs` may name: the ones that served each, and the one canopy asked for. */
export function runModelIds(runs: Iterable<Run>): string[] {
    const ids: string[] = []
    for (const run of runs) {
        if (run.model !== null) {
            ids.push(run.model)
        }
        if (run.models?.status === 'found') {
            ids.push(...run.models.models.map((m) => m.model))
        }
    }
    return ids
}

/**
 * Whether `model` ran `run`: it served the run, as its session says, or, until the session names any, canopy asked
 * for it. The runs page's `?model=` keeps these.
 */
export function ranOn(run: Run, model: string): boolean {
    const served = run.models?.status === 'found' ? run.models.models : []
    return served.length === 0 ? run.model === model : served.some((m) => m.model === model)
}

// A model's name after its provider, the first part of its id; an id with none is its own name.
function withoutProvider(id: string): string {
    const slash = id.indexOf('/')
    return slash === -1 ? id : id.slice(slash + 1)
}
