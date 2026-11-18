# canopy-codemods

The mechanical rewrites canopy's own Python is held to, built on [LibCST](https://libcst.readthedocs.io), which keeps
every comment and blank line a rewrite does not touch. It is a dev tool: canopy neither ships nor runs it, and it
imports nothing from canopy.

A convention a linter can only report, a codemod can also apply. Each one here is applied by `make fmt` and checked by
`make lint`, so the repository stays as the codemods leave it, and a change that drifts fails CI's lint with the diff
that fixes it.

```sh
uv run canopy-codemods .                    # rewrite every Python file under the repository (make fmt)
uv run canopy-codemods --check .            # change nothing: print the diff, exit 1 if there is one (make lint)
uv run canopy-codemods --only final-constants src/canopy/core/config.py
uv run canopy-codemods --list
```

A directory gives its `.py` files and its scripts that open with a Python shebang, such as the test fakes, but
nothing under a hidden directory, `node_modules`, or a build's output. A file named outright is taken as it is, which
is how the git hook (`prek.toml`) runs the codemods on a commit's files.

## The codemods

- **`final-constants`** annotates every module constant `Final`, so the type checker refuses a second assignment:
  `LIMIT = 3` becomes `LIMIT: Final = 3`, and `NAMES: Sequence[str] = ()` becomes `NAMES: Final[Sequence[str]] = ()`.
  A constant is an `UPPER_CASE` name bound once, by an assignment among the module's own statements. It leaves alone
  a lowercase name, which is how a module spells an object with state of its own (`_log`, `router`); a name bound
  again anywhere in the module (a second assignment, `+=`, `del`, a function's `global`); an object made to hold
  state whatever its name, such as a logger or a lock; and a `TypeVar` or an explicit `TypeAlias`.
- **`type-aliases`** spells an implicit type alias as a `type` statement, which ruff does only for one annotated
  `TypeAlias`: `Outcome = Literal["packed", "failed"]` becomes `type Outcome = Literal["packed", "failed"]`. An alias
  is a `CamelCase` name bound once, among the module's own statements, to a `Literal`, a `tuple`, a `Callable`, or a
  union of types. A `type` statement makes a `TypeAliasType`, not the type it names, so it leaves alone a name the
  module reads outside an annotation (passed to `get_args` or `isinstance`, called, subclassed, held in another
  assignment); an `Annotated[...]` alias, whose metadata frameworks read as the program runs; and a union that may be
  of values, with no `None`, subscript, or builtin type in it. It sees one module at a time: where another module
  reads a rewritten alias at run time, that reader takes its `__value__`.

## Adding one

1. Write a module in `src/canopy_codemods/` holding a subclass of `command.Command`, which is a
   `libcst.codemod.VisitorBasedCodemodCommand`: its `visit_` and `leave_` methods rewrite the tree, and
   `AddImportsVisitor.add_needed_import` adds an import it needs. Give it a `DESCRIPTION`.
2. Add it to `registry.CODEMODS` under the name the command line takes.
3. Test it in `tests/canopy_codemods/`, with its cases as Python snippets in `cases/<name>.md`: under a heading, two
   `python` blocks are a module's text before and after, and one is text it must leave alone. `helpers.cases(name)`
   reads them for the test module, which runs each through `run.rewrite(source, [name])`. ruff does not format that
   file, so a snippet stays as the codemod writes it.
4. Run `make fmt` and commit what it rewrote with the codemod, since the lint fails from then on wherever it would
   still change a file.

Two rules keep the check honest and quick:

- **A codemod leaves alone what it wrote.** `--check` fails on any diff, so a second run over its own output must
  change nothing, also once ruff has sorted the imports and formatted the result. A test holds every registered
  codemod to it.
- **Say cheaply when a file is not yours.** Parsing a module with LibCST and visiting it takes a few hundred times as
  long as reading it, and the lint runs every codemod over every file. `Command.wants(source)` answers from the text
  alone, before anything is parsed: `final-constants` decides from the stdlib's `ast`, so the whole repository checks
  in about a second. A codemod without a `wants` parses every file on every lint.

A rewrite to run once, such as a migration off an API, needs no entry in the registry: run its command over the
repository, commit the result, and leave it out, or delete it.
