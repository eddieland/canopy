// canopy's clock for a running agent (DESIGN §33): near the end of the run's time, one line on each tool call's result
// tells the agent the minutes left before canopy stops the run, so it keeps its work before the kill.
//
// The agent runtime loads it from canopy's snapshot of its definitions, inside every agent process, sandboxed or not
// (TRUST_MODEL T4). So it is plain JavaScript with no imports, which loads with no network, and it does as little as
// it can: it reads CANOPY_DEADLINE, the moment canopy kills the run in Unix seconds, and the clock, nothing else. It
// writes nothing, refuses no call, grants no tool, and keeps nothing but the sessions it has warned. It catches every
// error, since a hook that throws fails a call that has already run. Without the variable it adds nothing.
//
// The runtime calls every function the module exports as a plugin, so it exports one.

/** The share of the time the run had when this loaded that it warns in: its last fifth. */
const SHARE = 5;
/** The most seconds before the deadline it warns from, however long the run. */
const MOST_SECONDS = 600;
/** What every line of canopy's starts with, as the prompts name it. */
const MARK = "[canopy]";

/**
 * The plugin: the hook that tells a tool call's result the minutes left, or none without a deadline.
 *
 * It counts the warning's start from its own load, at the session's start, so it needs no second variable.
 *
 * @returns {Promise<object>} The plugin's hooks.
 */
export const CanopyClock = async () => {
    try {
        const deadline = readDeadline();
        if (deadline === null) {
            return {};
        }
        const loaded = Date.now() / 1000;
        const warnFrom = deadline - Math.min(Math.max(deadline - loaded, 0) / SHARE, MOST_SECONDS);
        const warned = new Set();
        return {
            "tool.execute.after": async (input, output) => {
                try {
                    const now = Date.now() / 1000;
                    if (now < warnFrom) {
                        return;
                    }
                    const session = input?.sessionID;
                    if (tell(output, line(deadline - now, !warned.has(session)))) {
                        warned.add(session);
                    }
                } catch {
                    // The call has already run: a warning that fails must not fail it.
                }
            },
        };
    } catch {
        return {};
    }
};

/** The deadline in Unix seconds, or null when the variable is unset or not a whole number of seconds. */
function readDeadline() {
    const raw = process.env.CANOPY_DEADLINE;
    if (typeof raw !== "string" || !/^[0-9]{1,15}$/.test(raw)) {
        return null;
    }
    return Number(raw);
}

/** The line for `left` seconds before the deadline: the minutes left, and the first time, what to do with them. */
function line(left, first) {
    const minutes = Math.floor(left / 60);
    const amount = minutes < 1 ? "less than a minute" : minutes === 1 ? "1 minute" : `${minutes} minutes`;
    const said = `${MARK} ${amount} left before canopy stops this run.`;
    if (!first) {
        return said;
    }
    return (
        `${said} Wrap up now: finish what keeps your work (commit and push it, or record your decisions), then print` +
        " your result line."
    );
}

/**
 * Add `text` to a tool call's result, in place, and return whether it could.
 *
 * An MCP tool's result is truncated after the hook keeping its head, so the line goes first in its `content`. A
 * built-in tool's goes after its `output`. A result of any other shape is left as it is.
 */
function tell(output, text) {
    if (output === null || typeof output !== "object") {
        return false;
    }
    if (Array.isArray(output.content)) {
        output.content.unshift({ type: "text", text });
        return true;
    }
    if (typeof output.output === "string") {
        const before = output.output;
        output.output = before === "" || before.endsWith("\n") ? `${before}${text}` : `${before}\n${text}`;
        return true;
    }
    return false;
}
