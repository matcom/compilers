# HULK Compiler Interface Contract

All submissions must implement this interface exactly for automated grading to work.

---

## Build

```bash
make build
```

- Must compile the project from source on **Ubuntu (latest LTS)**.
- Must produce a `./hulk` executable **in the repo root** after running.

## Invoke

```bash
./hulk <file.hulk>
```

**On success (exit 0):**

- Produces an executable `./output` in the current directory.
- `./output` must run on **Linux x86_64**.

**On error:**

Exits with the code corresponding to the first (most fundamental) error type found:

| Exit code | Error type |
|-----------|------------|
| `1` | Lexical error |
| `2` | Syntactic error |
| `3` | Semantic error |

Prints **one line per error** to **stderr** in the format:

```
(line,col) TYPE: message
```

- `line`, `col`: 1-based position of the first token attributable to the error.
- Use `(0,0)` if no sensible source position exists.
- `TYPE` is exactly one of: `LEXICAL`, `SYNTACTIC`, `SEMANTIC`.
- If errors of multiple types exist, the exit code reflects the most fundamental
  type (LEXICAL takes priority over SYNTACTIC, SYNTACTIC over SEMANTIC).

## Report

Your repository must contain a `REPORT.md` at the **repo root** with at least
**2000 words** describing your compiler's architecture, design decisions,
implemented features, and any notable limitations.

## Runtime errors

Runtime errors come from `./output` itself and are not tested at the compiler
level. The compiler only needs to produce a correct binary — what that binary
does is evaluated separately.

## Makefile example

A minimal `Makefile` that satisfies the contract (for a Rust project):

```makefile
build:
    cargo build --release
    cp target/release/my_compiler ./hulk
```

For C/C++:

```makefile
build:
    gcc -O2 -o hulk src/main.c src/lexer.c src/parser.c ...
```

## Error format example

Given `bad.hulk`:

```
let x = $invalid in print(x);
```

Running `./hulk bad.hulk` must exit `1` and write to stderr:

```
(1,9) LEXICAL: unexpected character '$'
```

Given `type_error.hulk`:

```
function add(x: Number, y: Number): Number { x + y; }
{ add("hello", 5); }
```

Running `./hulk type_error.hulk` must exit `3` and write to stderr:

```
(2,3) SEMANTIC: type mismatch — expected Number, got String
```

## Submission

Once your compiler satisfies this contract, open an issue in this repository
using the **"Project Submission"** template. The CI will automatically:

1. Clone your repo
2. Run `make build`
3. Check `REPORT.md`
4. Run the test suite
5. Post results as a comment

Comment `/regrade` on your issue after pushing fixes to re-run.
