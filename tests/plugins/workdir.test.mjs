// The directory, the fifth job of the plugin canopy ships for its agent runs (DESIGN §33), under Node's own test
// runner: `make test-plugin`.
// It is driven as OpenCode 1 drives it: its hook called before each tool call with the call's arguments, which the
// hook changes in place, since 1 runs the tool with the object it handed the hook. `canopy.test.mjs` drives it through
// OpenCode 2's entry point.

import assert from "node:assert/strict";
import { test } from "node:test";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const plugin = path.join(here, "..", "..", ".agents", "plugins", "canopy.js");
const { default: canopy } = await import(pathToFileURL(plugin).href);

/** Hand the hook a call of `tool` with `args`, as OpenCode 1 does, and return the arguments it runs with. */
async function before(args, tool = "bash") {
    const hooks = await canopy.server({});
    await hooks["tool.execute.before"]({ tool, sessionID: "ses_1", callID: "call_1" }, { args });
    return args;
}

test("a leading cd becomes the call's working directory, so the rest is checked from where it runs", async () => {
    assert.deepEqual(await before({ command: "cd app && cd ../lib" }), { command: "cd ../lib", workdir: "app" });
    assert.deepEqual(await before({ command: "  cd src/pkg&&\n  cat ../../README.md", description: "d" }), {
        command: "cat ../../README.md",
        description: "d",
        workdir: "src/pkg",
    });
});

test("each leading cd joins the one before it, onto the working directory the call names", async () => {
    const args = { command: "cd a && cd 'b c' && cd \"d\" && make test", workdir: "repo/" };
    assert.deepEqual(await before(args), { command: "make test", workdir: "repo/a/b c/d" });
    assert.deepEqual(await before({ command: "cd a && cd /abs && ls" }), { command: "ls", workdir: "/abs" });
});

test("a cd out of the directory moves as any other, so the runtime still refuses it", async () => {
    assert.deepEqual(await before({ command: "cd ../.. && git status" }), { command: "git status", workdir: "../.." });
});

test("OpenCode 2's shell tool is moved as 1's is", async () => {
    assert.deepEqual(await before({ command: "cd app && ls" }, "shell"), { command: "ls", workdir: "app" });
});

test("a command the shell would read otherwise is left as it is", async () => {
    const kept = [
        "cd app",
        "cd app && ",
        "cd app; ls",
        "cd app || ls",
        "cd - && ls",
        "cd ~/app && ls",
        "cd -P app && ls",
        "cd $HOME && ls",
        'cd "$DIR" && ls',
        'cd "a\\b" && ls',
        "cd '' && ls",
        "cd a*b && ls",
        "ls && cd app && ls",
        "cdx app && ls",
    ];
    for (const command of kept) {
        assert.deepEqual(await before({ command }), { command }, command);
    }
});

test("a call of another tool, or with no command it can read, is left as it is", async () => {
    assert.deepEqual(await before({ command: "cd app && ls" }, "read"), { command: "cd app && ls" });
    assert.deepEqual(await before({ command: ["cd", "app"] }), { command: ["cd", "app"] });
    const hooks = await canopy.server({});
    await assert.doesNotReject(hooks["tool.execute.before"](undefined, undefined));
    await assert.doesNotReject(hooks["tool.execute.before"]({ tool: "bash" }, { args: null }));
});
