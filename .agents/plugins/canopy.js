// canopy's plugin for a running agent: each job canopy asks of the agent process, as hooks the runtime calls. Its
// first job is the clock (DESIGN §33): near the end of the run's time, one line on each tool call's result tells the
// agent the minutes left before canopy stops the run, so it keeps its work before the kill.
//
// The agent runtime loads it from canopy's snapshot of its definitions, inside every agent process, sandboxed or not
// (TRUST_MODEL T4). So it is plain JavaScript that imports nothing but the runtime's own `node:fs`, and that only when
// a job reads a file canopy wrote, so it loads with no network; and each job does as little as it can: it reads only
// what it is handed for that job (the clock, CANOPY_DEADLINE and the time; the nudge, CANOPY_RUN_ID and each call's
// tool and session, and in a run that follows a plan, CANOPY_PLAN and the steps of each `status` call; the answer, the
// wrap-up, and the message, CANOPY_RUN_ID and each its one file canopy writes in the directory CANOPY_ANSWERS names;
// the directory, a shell call's command and working directory; the wait, the MCP servers' names and states and the
// tools' names; the refusal, a refused call's permission and resources), changes only what its hook is handed, writes
// no file, refuses no call, and grants no tool. Each job's hooks run in its own try, in the order of `JOBS`, so a job
// that throws neither fails a call that has already run nor keeps the jobs after it from theirs.
//
// Its second is the nudge (DESIGN §41): in a worker's, planner's, reviewer's, or one-off task's run, after a number of
// tool calls with no call of canopy's `status` tool, one line on the next tool call's result asks the agent to post an
// update of its progress; in a worker's run that follows an approved plan, the line also names the plan's file and the
// steps the worker last reported working and next.
//
// Its third is the answer (DESIGN §41): in a run that keeps its progress, when the operator has answered the question
// it asks, one line on the next tool call's result tells the agent the letter and the option it names, once.
//
// Its fourth is the directory (DESIGN §33): a shell command that opens with `cd <dir> &&` runs with that directory as
// its working directory instead, which the runtime checks as it checks the `cd`, so the rest of the command is checked
// from where it runs.
//
// Its fifth is the wrap-up (DESIGN §22): in a run that keeps its progress, once the operator stops its ticket and asks
// it to wrap up, one line on the next tool call's result asks the agent to keep its work and report its result.
//
// Its sixth is the message (DESIGN §44): in a worker's, planner's, or one-off task's run, once the operator sends it
// a message, one line on the next tool call's result says a message waits and names canopy's tool that returns it,
// once per message; the line carries none of the message's words, which come only from that tool.
//
// Its seventh is the wait (DESIGN §33): a session's first prompt waits until the tools of its MCP servers are
// registered, which the runtime does only after the server connects, so that the first model call is sent them
// (`mcpTools`).
//
// Its eighth is the refusal (DESIGN §33): a call the run's permission rules refuse, which the runtime reports to the
// agent as no more than `Permission denied:` and the permission, also says what it asked for and that the refusal is
// on purpose, not to be tried another way (`explain`); it reads the refusal's permission and resources, and changes
// only the reason the agent is told.
//
// OpenCode loads it by its one export, the default: its id, and `setup`, which registers the jobs' hooks. It calls no
// other export, so the file has none.
//
// Its types are JSDoc, checked by `make lint` against the pinned runtime's own plugin types (tests/plugins/): a type
// import in a comment is no import at all, so the file stays one the runtime loads with nothing installed.

// @ts-check

/** @typedef {import("@opencode/plugin").Plugin.Context} Context */
/** @typedef {Parameters<Parameters<Context["tool"]["hook"]>[1]>[0]} ToolEvent */
/** @typedef {Exclude<ToolEvent, { status: string }>} BeforeEvent */
/** @typedef {Extract<ToolEvent, { status: string }>} AfterEvent */
/** @typedef {Extract<AfterEvent, { status: "completed" }>["result"]} Result */
/** @typedef {Exclude<Result["content"], string | undefined>[number]} Content */
/** @typedef {{ name: string, status: { status: string } }} McpServer */
/**
 * A job's hooks, each called as the runtime calls its own: `prompt` before a session's prompt goes on, `before` each
 * tool call, whose input it may change in place, and `after` each, with the content of the call's result, to put a
 * line first in, or null for a call that failed, which has none.
 *
 * @typedef {object} Job
 * @property {() => Promise<void>} [prompt]
 * @property {(event: BeforeEvent) => Promise<void>} [before]
 * @property {(event: AfterEvent, content: Content[] | null) => Promise<void>} [after]
 */

/** The share of the time the run had when the clock loaded that it warns in: its last fifth. */
const SHARE = 5;
/** The most seconds before the deadline the clock warns from, however long the run. */
const MOST_SECONDS = 600;
/** What every line of canopy's starts with, as the prompts name it. */
const MARK = "[canopy]";
/** A run that keeps progress, as CANOPY_RUN_ID names it: a worker's or a planner's id, a review's, `review-7`, or a
 * task's, `task-3`. */
const CARD_RUN = /^(?:review-|task-)?[0-9]{1,18}$/;
/** One whose progress may ask the operator a question: any of those but a task's, which asks in its final line. */
const ASKING_RUN = /^(?:review-)?[0-9]{1,18}$/;
/** canopy's tool that posts an update of the run's progress, as the runtime names it. */
const STATUS_TOOL = "canopy_run_status";
/** How many tool calls a session makes before its first `status` call, before the nudge asks for one. */
const FIRST_CALLS = 8;
/** How many tool calls a session makes with no `status` call after its first, and after each time the nudge asked,
 * before the nudge asks again. */
const STALE_CALLS = 20;
/** The path of a worker's copy of its plan, as CANOPY_PLAN names it: absolute, on one line, and not too long. */
const PLAN_PATH = /^\/[^\x00-\x1f\x7f]{0,4095}$/;
/** The most steps a `status` call may carry, and the longest title one may have, as canopy's server holds them. */
const MOST_STEPS = 40;
const MOST_TITLE = 200;
/** The file in a run's answers directory that holds the operator's latest answer. */
const ANSWER_FILE = "answer.json";
/** The file in it that asks the agent to wrap up. */
const WRAP_UP_FILE = "wrap_up.json";
/** The file in it that marks the newest message the operator sent the run, by its id alone, never its text. */
const MESSAGE_FILE = "message.json";
/** A run that takes the operator's messages, as CANOPY_RUN_ID names it: a worker's or a planner's id, or a task's,
 * `task-3`. A review's takes none (DESIGN §44). */
const MESSAGE_RUN = /^(?:task-)?[0-9]{1,18}$/;
/** canopy's tool that returns the operator's messages to the run, as the runtime names it. */
const MESSAGES_TOOL = "canopy_run_messages";
/** The message's line, which the mark asks for: it names the tool, and says nothing of what the message says. */
const MESSAGE_WAITS =
    `${MARK} The operator sent you a message while you work: call ${MESSAGES_TOOL} to read it, then go on as it` +
    " says.";
/** The most of a file in it that is read: one longer is not canopy's. */
const FILE_BYTES = 4096;
/** The wrap-up's line, which the file asks for. */
const WRAP_UP =
    `${MARK} The operator stopped this ticket and asks you to wrap up now: finish what keeps your work (commit and` +
    " push it, or record your decisions), start nothing new, then report your result, its summary naming what" +
    " remains.";
/** The letter of a question's option. */
const LETTER = /^[A-E]$/;
/** The shell tool, by its name and by the other the runtime takes a call of it under. */
const SHELL_TOOLS = new Set(["shell", "bash"]);
/**
 * A command's leading `cd` and the `&&` after it: its directory written plainly, in single quotes, or in double quotes
 * with nothing the shell would expand, and the space after the `&&`, a newline included.
 */
const LEADING_CD = /^\s*cd[ \t]+(?:([\w./@%+=:,][\w./@%+=:,-]*)|'([^'\n]*)'|"([^"$`\\\n]*)")[ \t]*&&\s*/;
/** The longest a session's first prompt waits on MCP servers still connecting, in milliseconds. */
const MCP_WAIT_MS = 30_000;
/** The longest it waits, once none is connecting, for a connected server's tools to be registered. */
const MCP_SETTLE_MS = 2_000;
/** How often it asks the runtime again while it waits. */
const MCP_POLL_MS = 50;
/** The tag of the error the runtime fails a call with when the run's permission rules refuse it. */
const BLOCKED = "Permission.BlockedError";
/** The most of a refused call's resources the reason names, and the longest each is named, in characters. */
const MOST_RESOURCES = 3;
const MOST_RESOURCE = 200;
/** What the reason adds for a permission whose refusal says more than the line every refusal ends with. */
const REFUSED = new Map([
    ["external_directory", "It is outside the directories this run may reach."],
    ["webfetch", "This agent has no web tools."],
    ["websearch", "This agent has no web tools."],
    ["codesearch", "This agent has no web tools."],
    ["execute", "This agent has no code mode, which can reach the web."],
    ["task", "This agent starts no subagents."],
]);

/**
 * Each job the plugin does, in the order its hooks run: a function that returns its hooks.
 *
 * @type {Array<(ctx: Context) => Job>}
 */
const JOBS = [clock, nudge, answer, workdir, wrapUp, message, mcpTools, explain];

/**
 * The plugin, as OpenCode reads it: its id, and the entry point that registers its hooks.
 *
 * @type {import("@opencode/plugin").Plugin.Plugin}
 */
export default { id: "canopy", setup };

/**
 * The plugin's entry point: every job's hooks, each registered under the runtime's name for it.
 *
 * The runtime hands `execute.before` each call's input, which a job changes in place. It hands `execute.after` every
 * call, failed ones too, with the result as the tool returned it; it truncates the result after the hook, keeping its
 * head, whatever the tool. So the jobs get each successful call's content as a list (`contentOf`), to put a line first
 * in, and the hook puts that list back only when a job changed it. A failed call reaches them with no content, so the
 * nudge counts it and no job adds a line to it; one the permission rules refused is explained in its error (`explain`).
 *
 * @param {Context} ctx
 * @returns {Promise<void>}
 */
async function setup(ctx) {
    /** @type {Job[]} */
    const jobs = [];
    for (const job of JOBS) {
        try {
            jobs.push(job(ctx));
        } catch {
            // A job that cannot load has no hook, and the jobs after it still load.
        }
    }
    await ctx.session.hook("prompt", () => inTurn(jobs, (job) => job.prompt?.()));
    await ctx.tool.hook("execute.before", (event) => inTurn(jobs, (job) => job.before?.(event)));
    await ctx.tool.hook("execute.after", async (event) => {
        try {
            if (event.status !== "completed") {
                await inTurn(jobs, (job) => job.after?.(event, null));
                return;
            }
            const content = contentOf(event.result);
            const had = content.length;
            await inTurn(jobs, (job) => job.after?.(event, content));
            if (content.length !== had) {
                event.result = { ...event.result, content };
            }
        } catch {
            // A hook that throws fails the call it runs after.
        }
    });
}

/**
 * Call `hook` with each job in turn, each in its own try: a hook that throws fails the prompt or the call the runtime
 * called it for, and must not keep the next job from its own.
 *
 * @param {Job[]} jobs
 * @param {(job: Job) => Promise<void> | undefined} hook
 * @returns {Promise<void>}
 */
async function inTurn(jobs, hook) {
    for (const job of jobs) {
        try {
            await hook(job);
        } catch {
            // The next job's hook still runs.
        }
    }
}

/**
 * A result's content as the runtime sends it to the model: a string as one text, a list as it is, and, without
 * either, the output as text, a string as it is and anything else as JSON.
 *
 * @param {Result} result
 * @returns {Content[]}
 */
function contentOf(result) {
    const { content, output } = result;
    if (typeof content === "string") {
        return [{ type: "text", text: content }];
    }
    if (content !== undefined && content.length > 0) {
        return [...content];
    }
    let text;
    try {
        text = typeof output === "string" ? output : (JSON.stringify(output) ?? String(output));
    } catch {
        text = String(output);
    }
    return [{ type: "text", text }];
}

/**
 * The clock's hooks: the one that tells a tool call's result the minutes left, or none without a deadline.
 *
 * It counts the warning's start from its own load, at the session's start, so it needs no second variable.
 *
 * @returns {Job} The clock's hooks.
 */
function clock() {
    const deadline = readDeadline();
    if (deadline === null) {
        return {};
    }
    const loaded = Date.now() / 1000;
    const warnFrom = deadline - Math.min(Math.max(deadline - loaded, 0) / SHARE, MOST_SECONDS);
    /** @type {Set<string>} */
    const warned = new Set();
    return {
        after: async (event, content) => {
            const now = Date.now() / 1000;
            if (now < warnFrom) {
                return;
            }
            const session = event.sessionID;
            if (tell(content, line(deadline - now, !warned.has(session)))) {
                warned.add(session);
            }
        },
    };
}

/**
 * The deadline in Unix seconds, or null when the variable is unset or not a whole number of seconds.
 *
 * @returns {number | null}
 */
function readDeadline() {
    const raw = process.env.CANOPY_DEADLINE;
    if (typeof raw !== "string" || !/^[0-9]{1,15}$/.test(raw)) {
        return null;
    }
    return Number(raw);
}

/**
 * The line for `left` seconds before the deadline: the minutes left, and the first time, what to do with them.
 *
 * @param {number} left
 * @param {boolean} first
 * @returns {string}
 */
function line(left, first) {
    const minutes = Math.floor(left / 60);
    const amount = minutes < 1 ? "less than a minute" : minutes === 1 ? "1 minute" : `${minutes} minutes`;
    const said = `${MARK} ${amount} left before canopy stops this run.`;
    if (!first) {
        return said;
    }
    return (
        `${said} Wrap up now: finish what keeps your work (commit and push it, or record your decisions), then report` +
        " your result."
    );
}

/**
 * Add `text` to a tool call's result, and return whether it could: a failed call has no content to add it to.
 *
 * The runtime truncates a result after the hook, keeping its head, so the line goes first in its content.
 *
 * @param {Content[] | null} content
 * @param {string} text
 * @returns {boolean}
 */
function tell(content, text) {
    if (content === null) {
        return false;
    }
    content.unshift({ type: "text", text });
    return true;
}

/**
 * The steps a session last reported working and next, by the titles it gave them, either null when it reported none.
 *
 * @typedef {{ working: string | null, next: string | null }} Reported
 */

/**
 * The nudge's hooks: the one that asks for an update once a session has gone a while without one.
 *
 * A worker, a planner, a reviewer, or a task's worker keeps its progress, where its work stands, for the operator
 * (DESIGN §41), through canopy's `status` tool; one that forgets leaves the operator progress that says less each call,
 * or none at all. The nudge counts each session's tool calls since its last successful `status` call, or since it
 * started, and adds one line to a call's result asking for an update, the way the clock adds its line, so the agent
 * hears it between calls and never mid-thought: at `FIRST_CALLS` for a session that has posted none yet, so the
 * operator hears early what the work is, and at `STALE_CALLS` after its last. An agent that goes on without one is
 * asked again each `STALE_CALLS` calls after. It keeps, per session, the count, whether it has updated, and when it
 * last asked, and in a run that follows a plan the two steps below, and nothing else; in any other run, as
 * CANOPY_RUN_ID names it, it has no hook.
 *
 * A worker that follows an approved plan is told once, in its prompt, to take its steps from it (DESIGN §25); canopy
 * names its copy of the plan in CANOPY_PLAN. There the line also names that file, and the steps the session's last
 * successful `status` call reported working and next, by the titles it gave them, so the plan is restated through a
 * long run rather than read once. The line carries canopy's own words and the titles the worker itself reported, and a
 * forged one could only restate a step, so it fails safe as the ask does.
 *
 * @returns {Job} The nudge's hooks.
 */
function nudge() {
    const run = process.env.CANOPY_RUN_ID;
    if (typeof run !== "string" || !CARD_RUN.test(run)) {
        return {};
    }
    /** @type {Map<string, number>} */
    const since = new Map();
    /** @type {Set<string>} */
    const updated = new Set();
    /** @type {Map<string, number>} */
    const askedAt = new Map();
    const raw = process.env.CANOPY_PLAN;
    const plan = typeof raw === "string" && PLAN_PATH.test(raw) ? raw : null;
    /** @type {Map<string, Reported>} */
    const reported = new Map();
    return {
        after: async (event, content) => {
            const session = event.sessionID;
            // A `status` call the server refused, which failed, leaves the last update as old as it was.
            if (event.tool === STATUS_TOOL && event.status === "completed") {
                since.delete(session);
                askedAt.delete(session);
                updated.add(session);
                if (plan !== null) {
                    reported.set(session, stepsOf(event.input));
                }
                return;
            }
            const calls = (since.get(session) ?? 0) + 1;
            since.set(session, calls);
            const first = !updated.has(session);
            const last = askedAt.get(session);
            const due = last === undefined ? calls >= (first ? FIRST_CALLS : STALE_CALLS) : calls - last >= STALE_CALLS;
            if (due && tell(content, stale(calls, first) + planned(plan, reported.get(session)))) {
                askedAt.set(session, calls);
            }
        },
    };
}

/**
 * The nudge's line, after `calls` tool calls with no `status` call, `first` when the session has made none yet.
 *
 * @param {number} calls
 * @param {boolean} first
 * @returns {string}
 */
function stale(calls, first) {
    const lapse = first ? `${calls} tool calls and no update yet` : `${calls} tool calls since your last update`;
    return `${MARK} ${lapse}: call ${STATUS_TOOL} with where your work stands now, then go on.`;
}

/**
 * What the nudge's line adds in a run that follows a plan: the plan's file, and the steps last reported, if any; in
 * any other run, nothing.
 *
 * @param {string | null} plan
 * @param {Reported | undefined} steps
 * @returns {string}
 */
function planned(plan, steps) {
    if (plan === null) {
        return "";
    }
    const said = [];
    if (steps?.working) {
        said.push(`step "${steps.working}" working`);
    }
    if (steps?.next) {
        said.push(`step "${steps.next}" next`);
    }
    if (said.length === 0) {
        return ` Your plan is \`${plan}\`: take your steps from it.`;
    }
    return ` Your plan is \`${plan}\`; your last update had ${said.join(" and ")}.`;
}

/**
 * The steps a `status` call's input reports working and next: the first step working, and the first not started
 * after it, or the first not started when none is working. A call whose steps canopy's server would refuse, too many
 * or a title too long, reports none, and a title is one line, as the server makes it.
 *
 * @param {unknown} input
 * @returns {Reported}
 */
function stepsOf(input) {
    /** @type {Reported} */
    const none = { working: null, next: null };
    const steps = input !== null && typeof input === "object" && "steps" in input ? input.steps : undefined;
    if (!Array.isArray(steps) || steps.length > MOST_STEPS) {
        return none;
    }
    /** @type {Array<{ title: string, status: unknown }>} */
    const found = [];
    for (const step of steps) {
        const title = step !== null && typeof step === "object" ? step.title : undefined;
        if (typeof title !== "string" || title.length > MOST_TITLE) {
            return none;
        }
        found.push({ title: oneLine(title), status: step.status });
    }
    const at = found.findIndex((step) => step.status === "working");
    const next = found.find((step, index) => index > at && step.status === "not_started");
    return { working: found[at]?.title || null, next: next?.title || null };
}

/**
 * A title as one line, as canopy's server makes each line of an update: what is not printable made a space, and the
 * spaces collapsed.
 *
 * @param {string} title
 * @returns {string}
 */
function oneLine(title) {
    return title.replace(/\p{C}/gu, " ").split(/\s+/u).filter(Boolean).join(" ");
}

/**
 * The answer's hooks: the one that tells a tool call's result the operator's answer to the question the run asks.
 *
 * A worker, a planner, or a reviewer may ask the operator a question in its progress, with lettered options, and work
 * around it meanwhile (DESIGN §41). canopy writes the operator's answer, a letter, to a file in the run's answers
 * directory, which CANOPY_ANSWERS names and a sandboxed run may read but not write. After each tool call, the job
 * reads that file and, for an answer this session has not been told, adds one line to the call's result, the way the
 * clock adds its line, so the agent hears it between calls. A later answer, to the same question or another, is told
 * in turn. It keeps what it last told each session, and nothing else; without the variable, or in a run whose progress
 * asks nothing, it has no hook. A file it cannot read, or that is not an answer, tells nothing.
 *
 * @returns {Job} The answer's hooks.
 */
function answer() {
    const file = answersFile(ANSWER_FILE);
    if (file === null) {
        return {};
    }
    /** @type {Map<string, string>} */
    const told = new Map();
    return {
        after: async (event, content) => {
            const said = answerLine(await readOwn(file));
            const session = event.sessionID;
            if (said !== null && told.get(session) !== said && tell(content, said)) {
                told.set(session, said);
            }
        },
    };
}

/**
 * The path of the file `name` in the run's answers directory, or null in a run that has none: without CANOPY_ANSWERS,
 * or in a run whose progress asks nothing, as CANOPY_RUN_ID names it.
 *
 * @param {string} name
 * @returns {string | null}
 */
function answersFile(name) {
    const dir = process.env.CANOPY_ANSWERS;
    const run = process.env.CANOPY_RUN_ID;
    if (typeof dir !== "string" || !dir.startsWith("/") || typeof run !== "string" || !ASKING_RUN.test(run)) {
        return null;
    }
    return `${dir.replace(/\/+$/, "")}/${name}`;
}

/**
 * The text of a file canopy writes in the answers directory, or null when there is none to read, or it is too long to
 * be canopy's.
 *
 * @param {string} file
 * @returns {Promise<string | null>}
 */
async function readOwn(file) {
    try {
        const { readFile } = await import("node:fs/promises");
        const text = await readFile(file, "utf8");
        return text.length <= FILE_BYTES ? text : null;
    } catch {
        return null;
    }
}

/**
 * The line that tells the agent the answer in `text`, or null when `text` is no answer canopy writes.
 *
 * @param {string | null} text
 * @returns {string | null}
 */
function answerLine(text) {
    if (text === null) {
        return null;
    }
    let found;
    try {
        found = JSON.parse(text);
    } catch {
        return null;
    }
    if (found === null || typeof found !== "object") {
        return null;
    }
    const { ask, letter, option } = found;
    if (typeof ask !== "string" || typeof option !== "string" || typeof letter !== "string" || !LETTER.test(letter)) {
        return null;
    }
    return (
        `${MARK} The operator answers your question "${ask}": ${letter}, ${option}. Go on with it, and drop the` +
        " question from your next update."
    );
}

/**
 * The directory's hooks: the one that moves a shell command's leading `cd` into the call's working directory.
 *
 * Each shell call starts in the agent's directory, and the runtime checks every `cd` in it from there, not from where
 * an earlier `cd` in the same command went; so `cd app && cd ../lib`, which stays inside, is refused as leaving it, and
 * the refusal does not say why. A command that opens with `cd <dir> &&` runs the rest in that directory, as one with
 * that working directory does, so the job makes it one: it takes the leading `cd`s off the command and joins their
 * directories onto the call's working directory, and the runtime checks that directory, and the rest of the command
 * from it, as it checks any call's. So it reaches nothing the `cd` could not, and a `cd` out of the agent's directory
 * is refused as before. Only a directory written plainly moves, letters, digits, and `._/@%+=:,-`, or quoted with none
 * of `$`, `` ` ``, `\`, or a quote inside; anything else, `cd -`, `cd ~`, and a `cd` with an option among them, leaves
 * the command as it is. It reads and changes only the shell call's command and working directory.
 *
 * @returns {Job} The directory's hooks.
 */
function workdir() {
    return {
        before: async (event) => {
            const input = event.input;
            if (!SHELL_TOOLS.has(event.tool) || input === null || typeof input !== "object") {
                return;
            }
            const call = /** @type {{ command?: unknown, workdir?: unknown }} */ (input);
            if (typeof call.command !== "string") {
                return;
            }
            const moved = leadingCd(call.command);
            if (moved === null) {
                return;
            }
            let dir = typeof call.workdir === "string" && call.workdir !== "" ? call.workdir : null;
            for (const each of moved.dirs) {
                dir = dir === null || each.startsWith("/") ? each : `${dir.replace(/\/+$/, "")}/${each}`;
            }
            call.command = moved.rest;
            call.workdir = dir;
        },
    };
}

/**
 * The directories of a command's leading `cd`s, each joined by `&&`, and the command after them, or null when it opens
 * with none the job moves, or nothing follows them.
 *
 * @param {string} command
 * @returns {{ dirs: string[], rest: string } | null}
 */
function leadingCd(command) {
    /** @type {string[]} */
    const dirs = [];
    let rest = command;
    for (let found = LEADING_CD.exec(rest); found !== null; found = LEADING_CD.exec(rest)) {
        const [whole, plain, single, double] = found;
        dirs.push(plain ?? single ?? double ?? "");
        rest = rest.slice(whole.length);
    }
    if (dirs.length === 0 || rest.trim() === "" || dirs.includes("")) {
        return null;
    }
    return { dirs, rest };
}

/**
 * The wrap-up's hooks: the one that asks the agent to wrap up, once the operator stops its ticket so.
 *
 * `canopy stop --wrap-up` stops a ticket and asks the run working it to end soon, keeping its work, rather than finish
 * all of it or be killed with what it has not pushed (DESIGN §22). canopy writes when it asked to a file in the run's
 * answers directory, as it writes an answer; after each tool call, the job reads that file and, for an ask this
 * session has not been told, adds one line to the call's result, the way the clock adds its line. It keeps when it
 * last told each session, and nothing else; without the variable, or in a run whose progress asks nothing, it has no
 * hook. A file it cannot read, or that is not canopy's, tells nothing. A forged one could only ask the agent to end
 * early, which leaves its work kept, so it fails safe as the clock's line does (§33).
 *
 * @returns {Job} The wrap-up's hooks.
 */
function wrapUp() {
    const file = answersFile(WRAP_UP_FILE);
    if (file === null) {
        return {};
    }
    /** @type {Map<string, string>} */
    const told = new Map();
    return {
        after: async (event, content) => {
            const asked = askedAt(await readOwn(file));
            const session = event.sessionID;
            if (asked !== null && told.get(session) !== asked && tell(content, WRAP_UP)) {
                told.set(session, asked);
            }
        },
    };
}

/**
 * When the wrap-up file in `text` was asked, as canopy writes it, or null when `text` is no ask of canopy's.
 *
 * @param {string | null} text
 * @returns {string | null}
 */
function askedAt(text) {
    if (text === null) {
        return null;
    }
    let found;
    try {
        found = JSON.parse(text);
    } catch {
        return null;
    }
    if (found === null || typeof found !== "object" || typeof found.asked !== "string" || found.asked === "") {
        return null;
    }
    return found.asked;
}

/**
 * The message's hooks: the one that tells the agent a message from the operator waits, once per message per session.
 *
 * The operator may send a running worker, planner, or task's worker a message in their own words (DESIGN §44). canopy
 * writes the messages to the run's answers directory, which CANOPY_ANSWERS names and a sandboxed run may read but not
 * write, and beside them a mark, the newest message's id and nothing of its text. After each tool call, the job reads
 * the mark and, for a message this session has not been told of, adds one line to the call's result, the way the clock
 * adds its line, saying a message waits and which of canopy's tools returns it. It never reads the messages: their
 * words reach the agent only through that tool, over canopy's own server, so a forged line can only make the agent
 * spend a call to learn that nothing is new. It keeps the newest message it told each session of, and nothing else;
 * without the variable, or in a run that takes no message, as CANOPY_RUN_ID names it, it has no hook. A file it cannot
 * read, or that is not canopy's mark, tells nothing.
 *
 * @returns {Job} The message's hooks.
 */
function message() {
    const dir = process.env.CANOPY_ANSWERS;
    const run = process.env.CANOPY_RUN_ID;
    if (typeof dir !== "string" || !dir.startsWith("/") || typeof run !== "string" || !MESSAGE_RUN.test(run)) {
        return {};
    }
    const file = `${dir.replace(/\/+$/, "")}/${MESSAGE_FILE}`;
    /** @type {Map<string, number>} */
    const told = new Map();
    return {
        after: async (event, content) => {
            const newest = newestOf(await readOwn(file));
            const session = event.sessionID;
            if (newest !== null && told.get(session) !== newest && tell(content, MESSAGE_WAITS)) {
                told.set(session, newest);
            }
        },
    };
}

/**
 * The id of the newest message the mark in `text` names, as canopy writes it, or null when `text` is no mark of
 * canopy's.
 *
 * @param {string | null} text
 * @returns {number | null}
 */
function newestOf(text) {
    if (text === null) {
        return null;
    }
    let found;
    try {
        found = JSON.parse(text);
    } catch {
        return null;
    }
    if (found === null || typeof found !== "object" || !Number.isSafeInteger(found.newest) || found.newest < 1) {
        return null;
    }
    return found.newest;
}

/**
 * The wait's hooks: the one that holds a session's first prompt until its MCP servers' tools register.
 *
 * The runtime connects a session's MCP servers as it starts, and registers a server's tools only after the server
 * connects; the first model call is sent the tools registered when it is made, so without the wait it is sent none of
 * them, and the overseer, which acts only through canopy's MCP tools (DESIGN §27), would have nothing to call. The
 * prompt hook runs before that call, and the runtime waits on it. It waits while a server is still connecting, at most
 * `MCP_WAIT_MS`, then while a connected server has no tool registered, at most `MCP_SETTLE_MS` more, since a server
 * may have none; then the prompt goes on, as it would have. It reads the servers' names and states and the tools'
 * names, and changes nothing. Later prompts wait for nothing.
 *
 * @param {Context} ctx
 * @returns {Job} The wait's hooks.
 */
function mcpTools(ctx) {
    let waited = false;
    return {
        prompt: async () => {
            if (waited) {
                return;
            }
            waited = true;
            await untilRegistered(ctx);
        },
    };
}

/**
 * Wait until no MCP server is connecting and each connected one has a tool registered, or the time is up.
 *
 * A server's tools are registered under its name, each character but a letter, a digit, `_`, and `-` made `_`, then
 * `_` and the tool's name, as the runtime names them.
 *
 * @param {Context} ctx
 * @returns {Promise<void>}
 */
async function untilRegistered(ctx) {
    const start = Date.now();
    let settling = null;
    while (Date.now() - start < MCP_WAIT_MS) {
        /** @type {readonly McpServer[]} */
        const servers = (await ctx.mcp.list()).data;
        const ids = (await ctx.tool.list()).map((tool) => tool.id);
        const connecting = servers.some((server) => server.status.status === "pending");
        const unregistered = servers.some(
            (server) =>
                server.status.status === "connected" &&
                !ids.some((id) => id.startsWith(`${server.name.replace(/[^a-zA-Z0-9_-]/g, "_")}_`)),
        );
        if (!connecting && !unregistered) {
            return;
        }
        if (!connecting) {
            settling ??= Date.now();
            if (Date.now() - settling >= MCP_SETTLE_MS) {
                return;
            }
        }
        await new Promise((resolve) => setTimeout(resolve, MCP_POLL_MS));
    }
}

/**
 * The refusal's hooks: the one that tells an agent why a call was refused, in the reason the runtime tells it.
 *
 * The runtime fails a call its permission rules refuse with a `Permission.BlockedError` inside the call's error, and
 * tells the agent that error's reason, or, with none, `Permission denied:` and the permission alone: not what it asked
 * for, nor that the refusal is meant. An agent told only that tries the same another way, through another command or
 * tool, and spends its run on it. So the job sets the reason to the runtime's own words, the resources the call asked
 * for, and one line of canopy's: that the rules refuse it on purpose, not to try it another way, and to say in the
 * result what remains if the work cannot go on without it. It changes nothing else of the error, so the call stays
 * refused as the runtime refused it, and leaves an error of any other kind, or one already explained, as it is. A rule
 * the repository or the operator set (TRUST_MODEL T7) is explained as canopy's are: the line names the rules the run
 * is under, not whose they are.
 *
 * @returns {Job} The refusal's hooks.
 */
function explain() {
    return {
        after: async (event) => {
            if (event.status !== "error") {
                return;
            }
            const blocked = /** @type {unknown} */ (event.error.error);
            if (blocked === null || typeof blocked !== "object" || !("_tag" in blocked) || blocked._tag !== BLOCKED) {
                return;
            }
            const refused =
                /** @type {{ message?: unknown, permission?: unknown, resources?: unknown, reason?: unknown }} */ (
                    blocked
                );
            const said = typeof refused.message === "string" ? refused.message : "Permission denied.";
            if (said.includes(MARK)) {
                return;
            }
            const permission = typeof refused.permission === "string" ? refused.permission : "";
            refused.reason = `${said}${askedFor(refused.resources)}\n${refusal(permission)}`;
        },
    };
}

/**
 * What a refused call asked for, as the reason names it: up to `MOST_RESOURCES` of its resources, each on one line and
 * cut at `MOST_RESOURCE` characters, or nothing when it names none but the wildcard an MCP tool's call asks for.
 *
 * @param {unknown} resources
 * @returns {string}
 */
function askedFor(resources) {
    if (!Array.isArray(resources)) {
        return "";
    }
    const named = resources
        .filter((resource) => typeof resource === "string" && resource !== "" && resource !== "*")
        .map((resource) => {
            const line = oneLine(resource);
            return line.length > MOST_RESOURCE ? `${line.slice(0, MOST_RESOURCE)}…` : line;
        });
    if (named.length === 0) {
        return "";
    }
    const more = named.length > MOST_RESOURCES ? `, and ${named.length - MOST_RESOURCES} more` : "";
    return ` (${named
        .slice(0, MOST_RESOURCES)
        .map((resource) => `\`${resource}\``)
        .join(", ")}${more})`;
}

/**
 * canopy's line on a refusal of `permission`: what that permission's refusal means, when it says more, and what every
 * refusal asks of the agent.
 *
 * @param {string} permission
 * @returns {string}
 */
function refusal(permission) {
    const means = REFUSED.get(permission);
    return (
        `${MARK} ${means === undefined ? "" : `${means} `}The rules this run is under refuse it on purpose; it is not` +
        " a fault to fix. Do not try it another way, through another command, a script, or another tool. If your" +
        " work cannot go on without it, finish what you can and say what remains in your result."
    );
}
