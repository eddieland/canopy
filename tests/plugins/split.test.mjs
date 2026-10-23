// The split, the second job of the plugin canopy ships for its agent runs (DESIGN §33), under Node's own test runner:
// `make test-plugin`.
// It is driven as OpenCode 1 drives it: its hook called before each model call with the system prompt as one string in
// an array, which the hook changes in place. The prompts are built as OpenCode 1.19.3's `session/llm/request.ts` and
// `session/system.ts` build them: the agent's body, then the environment, the instructions, and the skills, joined by
// newlines.

import assert from "node:assert/strict";
import { test } from "node:test";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const plugin = path.join(here, "..", "..", ".agents", "plugins", "canopy.js");
const { default: canopy } = await import(pathToFileURL(plugin).href);

const BODY = "You are canopy's worker.\n\nDo the ticket in your message, and print your result line last.";

/** The environment OpenCode 1 writes after the body, for a run started in `directory`. */
function environment(directory, date = "Fri Oct 23 2026") {
    return [
        "You are powered by the model named claude-x. The exact model ID is anthropic/claude-x",
        "Here is some useful information about the environment you are running in:",
        "<env>",
        `  Working directory: ${directory}`,
        `  Workspace root folder: ${directory}`,
        "  Is directory a git repo: yes",
        "  Platform: linux",
        `  Today's date: ${date}`,
        "</env>",
    ].join("\n");
}

/** The system prompt of a run of the worker in `directory`, as OpenCode 1 hands the hook it. */
function prompt(directory, date) {
    const instructions = `Instructions from: ${directory}/AGENTS.md\nRun the tests.`;
    const skills = "Skills provide specialized instructions and workflows for specific tasks.\n<available_skills/>";
    return [BODY, environment(directory, date), instructions, skills].join("\n");
}

/** Run the hook on `system`, as OpenCode 1 does, and return the array it handed it. */
async function transform(system) {
    const hooks = await canopy.server({});
    const output = { system };
    await hooks["experimental.chat.system.transform"]({ sessionID: "ses_1", model: {} }, output);
    return output.system;
}

test("the system prompt is cut after the body, in the array OpenCode handed it, and joins back as it was", async () => {
    const whole = prompt("/slots/api-1");
    const system = [whole];
    const after = await transform(system);
    assert.equal(after, system);
    assert.equal(after.length, 2);
    assert.equal(after[0], BODY);
    assert.match(after[1], /^You are powered by the model named claude-x\. /);
    assert.equal(after.join("\n"), whole);
});

test("two runs that differ only in their directory and date get the same first part", async () => {
    const [one] = await transform([prompt("/slots/api-1", "Fri Oct 23 2026")]);
    const [two] = await transform([prompt("/reviews/41", "Sat Oct 24 2026")]);
    assert.equal(one, two);
});

test("a body that quotes the model's line is still cut only where the environment starts", async () => {
    const quoting = `${BODY}\nYou are powered by the model named claude-x. Say so if asked.`;
    const whole = [quoting, environment("/slots/api-1")].join("\n");
    const after = await transform([whole]);
    assert.deepEqual(after, [quoting, environment("/slots/api-1")]);
});

test("a prompt with no environment, one that starts with it, or one already in parts is left as it is", async () => {
    const cases = [
        ["You generate titles.\nGenerate a title for this conversation."],
        [environment("/slots/api-1")],
        [BODY, environment("/slots/api-1")],
        [],
        [42],
    ];
    for (const system of cases) {
        const before = [...system];
        assert.deepEqual(await transform(system), before);
    }
});

test("no throw on an output of any shape, or one that cannot be read", async () => {
    const hooks = await canopy.server({});
    const hook = hooks["experimental.chat.system.transform"];
    const odd = [
        undefined,
        null,
        "text",
        {},
        { system: "not a list" },
        { system: Object.freeze([prompt("/slots/api-1")]) },
        Object.defineProperty({}, "system", {
            get() {
                throw new Error("a system that cannot be read");
            },
        }),
    ];
    for (const output of odd) {
        await assert.doesNotReject(hook(undefined, output));
    }
});
