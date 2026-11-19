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
- **`doc-comments`** writes the comment directly above a name as a Sphinx doc comment, which editors and doc tools
  attach to the name: `# How often a run is resumed.` above `MAX_RESUMES: Final = 3` becomes
  `#: How often a run is resumed.`. The names are a module's constants and type aliases, among its own statements, and
  the fields of a `@dataclass`, a `NamedTuple`, or an enum. It leaves alone a field of any other class, since a
  pydantic model's description is the docstring below its field and a `#` above one is a note kept out of the schema;
  a comment above a function, an import, or a lowercase module object; a block that holds a `#:` line already, a
  directive to a tool (`# noqa`, `# type:`, `# fmt:`), or a section's banner; and a comment a blank line separates
  from the name. It cannot tell what a name is from why the code is so, so a note of the second kind is written with
  a blank line below it, or beside the value. The colon can push a line past 120 columns, which the lint then reports.
- **`vocab-members`** names a closed vocabulary's member where canopy's code compares a bare string with a status, a
  kind, or a phase: `run.status == "running"` becomes `run.status == RunStatus.RUNNING`, and the vocabulary is imported
  at run time, out of an `if TYPE_CHECKING:` block if need be. It reads the vocabularies from `core/vocab.py` and the
  row types from `core/records` by the stdlib's `ast`, and rewrites a string compared by `==`, `!=`, `in`, or a
  `case` only where it is tied to one vocabulary without inferring a type: a name annotated with the vocabulary in the
  same function, or `self.field` of a class that annotates the field so; a field of a name annotated with a row type
  (`run: records.Run`); or a name or attribute called `status`, `kind`, or `phase` with strings one vocabulary alone
  holds, one whose name ends with that word and that the module imports already. It leaves alone a string several
  vocabularies hold where nothing ties it to one, a name annotated with anything else (`str`, a `Literal`, a union), a
  string the vocabulary does not hold, and any string outside a comparison. It covers canopy's own modules alone,
  under `src/canopy`: the tests assert on the string on purpose, and the other programs import nothing from canopy.

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
  in about a second. A codemod without a `wants` parses every file on every lint. A codemod held to some files alone
  says which in `Command.covers(filename)`, asked before the text is read: `vocab-members` covers `src/canopy`.

A rewrite to run once, such as a migration off an API, needs no entry in the registry: run its command over the
repository, commit the result, and leave it out, or delete it.
