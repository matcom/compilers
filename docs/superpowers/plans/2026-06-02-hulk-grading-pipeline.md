# HULK Grading Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Automated end-to-end HULK compiler tester that runs on CI when a student opens a GitHub issue, gives pass/fail feedback per category, and gates Alex's manual review on a green run.

**Architecture:** Students submit a GitHub issue with a structured template; a GitHub Actions workflow clones their repo, calls `make build` + `./hulk`, runs a curated test suite, and posts a results table as an issue comment. No reference implementation needed — tests are self-contained HULK programs with expected outputs.

**Tech Stack:** GitHub Actions, bash, HULK test programs, gh CLI for issue comments.

---

## Files to create

| File | Purpose |
|------|---------|
| `docs/interface.md` | Compiler contract for students |
| `.github/ISSUE_TEMPLATE/grading.yml` | Submission template (auto-labels `grading`) |
| `.github/workflows/grade.yml` | CI workflow |
| `tests/hulk/ok/minimal/*.hulk` + `*.expected` | 6 minimal feature tests |
| `tests/hulk/ok/types/*.hulk` + `*.expected` | 3 type system tests |
| `tests/hulk/ok/oop/*.hulk` + `*.expected` | 3 OOP tests |
| `tests/hulk/ok/extras/*.hulk` + `*.expected` | 2 bonus tests |
| `tests/hulk/errors/lexical/*.hulk` + `*.exit` | 2 lexical error tests |
| `tests/hulk/errors/syntactic/*.hulk` + `*.exit` | 2 syntactic error tests |
| `tests/hulk/errors/semantic/*.hulk` + `*.exit` | 3 semantic error tests |
| `tests/hulk/run_tests.sh` | Local test runner (mirrors CI logic) |

---

## Task 1: Compiler Interface Contract

**Files:**
- Create: `docs/interface.md`

- [ ] **Step 1: Write docs/interface.md**

```markdown
# HULK Compiler Interface Contract

All submissions must implement this interface exactly for automated grading.

## Build

```bash
make build
```

- Must compile the project from source on Ubuntu (latest LTS).
- Must produce a `./hulk` executable **in the repo root**.

## Invoke

```bash
./hulk <file.hulk>
```

**On success (exit 0):**
- Produces `./output` executable in the current directory (Linux x86_64).

**On error:**

Exits with the code corresponding to the error type:

| Code | Type |
|------|------|
| 1 | `LEXICAL` |
| 2 | `SYNTACTIC` |
| 3 | `SEMANTIC` |

Prints **one line per error** to **stderr**:

```
(line,col) TYPE: message
```

- `line`, `col`: 1-based position of the first token attributable to the error.
- Use `(0,0)` if there is no sensible position.
- `TYPE`: exactly `LEXICAL`, `SYNTACTIC`, or `SEMANTIC`.
- If errors of multiple types exist, exit code reflects the most fundamental type
  (LEXICAL takes priority over SYNTACTIC, SYNTACTIC over SEMANTIC).

## Report

Your repository must contain a `REPORT.md` at the root with at least 2000 words
describing your compiler architecture, design decisions, and any extra features.

## Example

Given `hello.hulk`:
```
print("Hello, World!");
```

Running `./hulk hello.hulk` exits 0 and creates `./output`.
Running `./output` prints `Hello, World!` followed by a newline.

Given `bad.hulk`:
```
let x = $invalid in print(x);
```

Running `./hulk bad.hulk` exits 1 and writes to stderr:
```
(1,9) LEXICAL: unexpected character '$'
```
```

- [ ] **Step 2: Commit**

```bash
git add docs/interface.md
git commit -m "docs(grading): add compiler interface contract"
```

---

## Task 2: Issue Template

**Files:**
- Create: `.github/ISSUE_TEMPLATE/grading.yml`

- [ ] **Step 1: Write grading.yml**

```yaml
name: 🎓 Project Submission
description: Submit your HULK compiler for automated grading
title: "[Grading] Team: "
labels: ["grading"]
body:
  - type: markdown
    attributes:
      value: |
        Fill in all fields. The CI will clone your repo, build your compiler,
        run the test suite, and post results as a comment on this issue.
        Fix any failures and comment `/regrade` to re-run.

  - type: input
    id: repo_url
    attributes:
      label: Repository URL
      description: Full URL of your public GitHub repository
      placeholder: https://github.com/username/HULK-Compiler
    validations:
      required: true

  - type: input
    id: branch
    attributes:
      label: Branch
      description: Branch to evaluate (default main)
      placeholder: main
    validations:
      required: true

  - type: textarea
    id: team
    attributes:
      label: Team Members
      description: Full name of each team member, one per line
      placeholder: |
        Fulano de Tal
        Mengana García
    validations:
      required: true

  - type: checkboxes
    id: features
    attributes:
      label: Features Implemented
      description: Check all that apply (be honest — unimplemented features will fail tests)
      options:
        - label: Minimal requirements (expressions, functions, variables, conditionals, loops)
        - label: Type system and type checking
        - label: OOP (classes, inheritance, polymorphism)
        - label: Iterables / for loops
        - label: Vectors / arrays
        - label: Protocols
        - label: Functors
        - label: Macros
```

- [ ] **Step 2: Commit**

```bash
git add .github/ISSUE_TEMPLATE/grading.yml
git commit -m "feat(grading): add structured submission issue template"
```

---

## Task 3: Test Suite — ok/minimal (6 tests)

**Files:** `tests/hulk/ok/minimal/*.hulk` + `*.expected`

- [ ] **Step 1: hello.hulk**

```hulk
print("Hello, World!");
```
Expected (`hello.expected`):
```
Hello, World!
```

- [ ] **Step 2: arithmetic.hulk**

```hulk
{
    if (2 + 3 * 4 == 14) print("ok") else print("fail");
    if (10 % 3 == 1) print("ok") else print("fail");
    if (2 ^ 10 == 1024) print("ok") else print("fail");
    if (10 / 2 == 5) print("ok") else print("fail");
    if (!(3 < 2)) print("ok") else print("fail");
};
```
Expected (`arithmetic.expected`):
```
ok
ok
ok
ok
ok
```

- [ ] **Step 3: strings.hulk**

```hulk
{
    print("Hello" @@ ", " @@ "World!");
    print("foo" @@ "bar");
};
```
Expected (`strings.expected`):
```
Hello, World!
foobar
```

- [ ] **Step 4: functions.hulk**

```hulk
function double(x: Number): Number {
    x * 2;
}

function greet(name: String): String {
    "Hello, " @@ name @@ "!";
}

function fib(n: Number): Number {
    if (n <= 1) n else fib(n-1) + fib(n-2);
}

{
    if (double(7) == 14) print("ok") else print("fail");
    if (fib(10) == 55) print("ok") else print("fail");
    print(greet("HULK"));
};
```
Expected (`functions.expected`):
```
ok
ok
Hello, HULK!
```

- [ ] **Step 5: let_binding.hulk**

```hulk
let x = 10, y = 20 in {
    if (x + y == 30) print("ok") else print("fail");
    let z = x * y in
        if (z == 200) print("ok") else print("fail");
};
```
Expected (`let_binding.expected`):
```
ok
ok
```

- [ ] **Step 6: conditionals.hulk**

```hulk
function classify(n: Number): String {
    if (n < 0) "negative"
    elif (n == 0) "zero"
    else "positive";
}

{
    print(classify(-5));
    print(classify(0));
    print(classify(42));
};
```
Expected (`conditionals.expected`):
```
negative
zero
positive
```

- [ ] **Step 7: while_loop.hulk**

```hulk
let i = 0 in
let result = 0 in {
    while (i < 5) {
        result := result + i;
        i := i + 1;
    };
    if (result == 10) print("ok") else print("fail");
    if (i == 5) print("ok") else print("fail");
};
```
Expected (`while_loop.expected`):
```
ok
ok
```

- [ ] **Step 8: Commit**

```bash
git add tests/hulk/ok/minimal/
git commit -m "test(grading): add ok/minimal test suite (7 tests)"
```

---

## Task 4: Test Suite — ok/types (3 tests)

**Files:** `tests/hulk/ok/types/*.hulk` + `*.expected`

- [ ] **Step 1: annotated.hulk**

```hulk
function add(x: Number, y: Number): Number {
    x + y;
}

function negate(b: Boolean): Boolean {
    !b;
}

{
    if (add(3, 4) == 7) print("ok") else print("fail");
    if (negate(false)) print("ok") else print("fail");
    if (add(0, 0) == 0) print("ok") else print("fail");
};
```
Expected (`annotated.expected`):
```
ok
ok
ok
```

- [ ] **Step 2: inference.hulk**

```hulk
function square(x) {
    x * x;
}

function identity(x) {
    x;
}

{
    if (square(5) == 25) print("ok") else print("fail");
    if (square(3) == 9) print("ok") else print("fail");
    if (identity(42) == 42) print("ok") else print("fail");
};
```
Expected (`inference.expected`):
```
ok
ok
ok
```

- [ ] **Step 3: builtins.hulk**

```hulk
{
    if (sqrt(9) == 3) print("ok") else print("fail");
    if (sqrt(4) == 2) print("ok") else print("fail");
    if (sin(0) == 0) print("ok") else print("fail");
    if (cos(0) == 1) print("ok") else print("fail");
};
```
Expected (`builtins.expected`):
```
ok
ok
ok
ok
```

- [ ] **Step 4: Commit**

```bash
git add tests/hulk/ok/types/
git commit -m "test(grading): add ok/types test suite (3 tests)"
```

---

## Task 5: Test Suite — ok/oop (3 tests)

**Files:** `tests/hulk/ok/oop/*.hulk` + `*.expected`

- [ ] **Step 1: basic_class.hulk**

```hulk
type Point(x_val: Number, y_val: Number) {
    x: Number = x_val;
    y: Number = y_val;

    getX(): Number => self.x;
    getY(): Number => self.y;
    sum(): Number => self.x + self.y;
}

let p = new Point(3, 4) in {
    if (p.getX() == 3) print("ok") else print("fail");
    if (p.getY() == 4) print("ok") else print("fail");
    if (p.sum() == 7) print("ok") else print("fail");
};
```
Expected (`basic_class.expected`):
```
ok
ok
ok
```

- [ ] **Step 2: inheritance.hulk**

```hulk
type Animal(n: String) {
    name: String = n;
    sound(): String { "..."; }
}

type Dog(n: String) inherits Animal(n) {
    sound(): String { "Woof"; }
}

type Cat(n: String) inherits Animal(n) {
    sound(): String { "Meow"; }
}

{
    let d = new Dog("Rex") in print(d.sound());
    let c = new Cat("Whiskers") in print(c.sound());
    let a: Animal = new Dog("Buddy") in print(a.sound());
};
```
Expected (`inheritance.expected`):
```
Woof
Meow
Woof
```

- [ ] **Step 3: mutation.hulk**

```hulk
type Counter(start: Number) {
    val = start;

    current(): Number => self.val;
    increment() => self.val := self.val + 1;
    add(n: Number) => self.val := self.val + n;
}

let c = new Counter(0) in {
    c.increment();
    c.increment();
    c.add(3);
    if (c.current() == 5) print("ok") else print("fail");
};
```
Expected (`mutation.expected`):
```
ok
```

- [ ] **Step 4: Commit**

```bash
git add tests/hulk/ok/oop/
git commit -m "test(grading): add ok/oop test suite (3 tests)"
```

---

## Task 6: Test Suite — ok/extras (2 bonus tests)

**Files:** `tests/hulk/ok/extras/*.hulk` + `*.expected`

- [ ] **Step 1: for_loop.hulk**

```hulk
let sum = 0 in {
    for (x in range(0, 5)) {
        sum := sum + x;
    };
    if (sum == 10) print("ok") else print("fail");
};
```
Expected (`for_loop.expected`):
```
ok
```

- [ ] **Step 2: range_count.hulk**

```hulk
let count = 0 in {
    for (i in range(0, 10)) {
        count := count + 1;
    };
    if (count == 10) print("ok") else print("fail");
};
```
Expected (`range_count.expected`):
```
ok
```

- [ ] **Step 3: Commit**

```bash
git add tests/hulk/ok/extras/
git commit -m "test(grading): add ok/extras bonus tests (2 tests)"
```

---

## Task 7: Test Suite — errors/* (7 tests)

**Files:** `tests/hulk/errors/**/*.hulk` + `*.exit`

- [ ] **Step 1: errors/lexical/invalid_char.hulk** (exit: 1)

```hulk
let x = $5 in print(x);
```
`invalid_char.exit`: `1`

- [ ] **Step 2: errors/lexical/bad_string.hulk** (exit: 1)

```hulk
let x = "unterminated
in print(x);
```
`bad_string.exit`: `1`

- [ ] **Step 3: errors/syntactic/missing_parens.hulk** (exit: 2)

```hulk
let x = 5 in
    if x > 3 print("ok");
```
`missing_parens.exit`: `2`

- [ ] **Step 4: errors/syntactic/invalid_assignment.hulk** (exit: 2)

```hulk
let 42 = x in print(x);
```
`invalid_assignment.exit`: `2`

- [ ] **Step 5: errors/semantic/undeclared_var.hulk** (exit: 3)

```hulk
let x = 5 in print(y);
```
`undeclared_var.exit`: `3`

- [ ] **Step 6: errors/semantic/type_mismatch.hulk** (exit: 3)

```hulk
function add(x: Number, y: Number): Number {
    x + y;
}

{
    add("hello", 5);
};
```
`type_mismatch.exit`: `3`

- [ ] **Step 7: errors/semantic/wrong_arity.hulk** (exit: 3)

```hulk
function add(x: Number, y: Number): Number {
    x + y;
}

{
    add(1, 2, 3);
};
```
`wrong_arity.exit`: `3`

- [ ] **Step 8: Commit**

```bash
git add tests/hulk/errors/
git commit -m "test(grading): add error test suite (7 tests: 2 lexical, 2 syntactic, 3 semantic)"
```

---

## Task 8: Local Test Runner

**Files:**
- Create: `tests/hulk/run_tests.sh`

- [ ] **Step 1: Write run_tests.sh**

```bash
#!/bin/bash
# run_tests.sh <student_repo_path> <tests_dir>
# Runs the HULK grading suite against a student compiler.
# Outputs a summary to stdout; exits 0 if all required tests pass, 1 otherwise.

set -euo pipefail

STUDENT_REPO="${1:?Usage: run_tests.sh <student_repo_path> <tests_dir>}"
TESTS_DIR="${2:?Usage: run_tests.sh <student_repo_path> <tests_dir>}"
HULK="$STUDENT_REPO/hulk"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'

declare -A CAT_PASS CAT_FAIL
TOTAL_PASS=0
TOTAL_FAIL=0
FAILURES=""

log_pass() { local cat="$1" name="$2"
    echo -e "${GREEN}PASS${NC} $cat/$name"
    CAT_PASS[$cat]=$(( ${CAT_PASS[$cat]:-0} + 1 ))
    TOTAL_PASS=$(( TOTAL_PASS + 1 ))
}

log_fail() { local cat="$1" name="$2" reason="$3"
    echo -e "${RED}FAIL${NC} $cat/$name: $reason"
    CAT_FAIL[$cat]=$(( ${CAT_FAIL[$cat]:-0} + 1 ))
    TOTAL_FAIL=$(( TOTAL_FAIL + 1 ))
    FAILURES="$FAILURES\n- \`$cat/$name\`: $reason"
}

run_ok_test() {
    local hulk_file="$1" expected_file="$2" cat="$3" name="$4"
    local tmpout; tmpout=$(mktemp)
    local tmperr; tmperr=$(mktemp)

    # Compile
    if ! (cd "$STUDENT_REPO" && ./hulk "$hulk_file" > "$tmpout" 2> "$tmperr"); then
        log_fail "$cat" "$name" "compilation failed (exit $(cd "$STUDENT_REPO" && ./hulk "$hulk_file" > /dev/null 2>&1; echo $?))"; rm -f "$tmpout" "$tmperr"; return
    fi

    # Run
    local actual; actual=$(cd "$STUDENT_REPO" && ./output 2>/dev/null) || {
        log_fail "$cat" "$name" "runtime error (./output crashed)"; rm -f "$tmpout" "$tmperr"; return
    }

    # Compare
    local expected; expected=$(cat "$expected_file")
    if [ "$actual" = "$expected" ]; then
        log_pass "$cat" "$name"
    else
        local got_preview; got_preview=$(echo "$actual" | head -3 | tr '\n' '|')
        local exp_preview; exp_preview=$(echo "$expected" | head -3 | tr '\n' '|')
        log_fail "$cat" "$name" "expected \`$exp_preview\`, got \`$got_preview\`"
    fi
    rm -f "$tmpout" "$tmperr"
}

run_error_test() {
    local hulk_file="$1" exit_file="$2" cat="$3" name="$4"
    local expected_exit; expected_exit=$(cat "$exit_file" | tr -d '[:space:]')

    # Map category to expected TYPE keyword
    local expected_type
    case "$cat" in
        errors/lexical)   expected_type="LEXICAL" ;;
        errors/syntactic) expected_type="SYNTACTIC" ;;
        errors/semantic)  expected_type="SEMANTIC" ;;
        *) expected_type="" ;;
    esac

    local tmperr; tmperr=$(mktemp)
    local actual_exit=0
    (cd "$STUDENT_REPO" && ./hulk "$hulk_file" > /dev/null 2> "$tmperr") || actual_exit=$?
    local stderr_out; stderr_out=$(cat "$tmperr"); rm -f "$tmperr"

    if [ "$actual_exit" != "$expected_exit" ]; then
        log_fail "$cat" "$name" "expected exit $expected_exit, got $actual_exit"
        return
    fi
    if [ -n "$expected_type" ] && ! echo "$stderr_out" | grep -q "$expected_type"; then
        log_fail "$cat" "$name" "exit $actual_exit OK but missing $expected_type in stderr"
        return
    fi
    log_pass "$cat" "$name"
}

# Check binary exists
if [ ! -f "$HULK" ]; then
    echo "ERROR: $HULK not found. Did make build succeed?" >&2
    exit 2
fi
chmod +x "$HULK"

# Run all test categories
for hulk_file in "$TESTS_DIR/ok/minimal/"*.hulk; do
    name=$(basename "$hulk_file" .hulk)
    expected="$TESTS_DIR/ok/minimal/$name.expected"
    run_ok_test "$hulk_file" "$expected" "ok/minimal" "$name"
done

for hulk_file in "$TESTS_DIR/ok/types/"*.hulk; do
    name=$(basename "$hulk_file" .hulk)
    expected="$TESTS_DIR/ok/types/$name.expected"
    run_ok_test "$hulk_file" "$expected" "ok/types" "$name"
done

for hulk_file in "$TESTS_DIR/ok/oop/"*.hulk; do
    name=$(basename "$hulk_file" .hulk)
    expected="$TESTS_DIR/ok/oop/$name.expected"
    run_ok_test "$hulk_file" "$expected" "ok/oop" "$name"
done

for hulk_file in "$TESTS_DIR/ok/extras/"*.hulk; do
    name=$(basename "$hulk_file" .hulk)
    expected="$TESTS_DIR/ok/extras/$name.expected"
    run_ok_test "$hulk_file" "$expected" "ok/extras" "$name"
done

for hulk_file in "$TESTS_DIR/errors/lexical/"*.hulk; do
    name=$(basename "$hulk_file" .hulk)
    exit_file="$TESTS_DIR/errors/lexical/$name.exit"
    run_error_test "$hulk_file" "$exit_file" "errors/lexical" "$name"
done

for hulk_file in "$TESTS_DIR/errors/syntactic/"*.hulk; do
    name=$(basename "$hulk_file" .hulk)
    exit_file="$TESTS_DIR/errors/syntactic/$name.exit"
    run_error_test "$hulk_file" "$exit_file" "errors/syntactic" "$name"
done

for hulk_file in "$TESTS_DIR/errors/semantic/"*.hulk; do
    name=$(basename "$hulk_file" .hulk)
    exit_file="$TESTS_DIR/errors/semantic/$name.exit"
    run_error_test "$hulk_file" "$exit_file" "errors/semantic" "$name"
done

# Summary
echo ""
echo "=============================="
echo "       GRADING SUMMARY"
echo "=============================="

REQUIRED_CATEGORIES=("ok/minimal" "ok/types" "ok/oop" "errors/lexical" "errors/syntactic" "errors/semantic")
ALL_GREEN=true

printf "%-25s %s\n" "Category" "Result"
printf "%-25s %s\n" "--------" "------"
for cat in "${REQUIRED_CATEGORIES[@]}" "ok/extras"; do
    p=${CAT_PASS[$cat]:-0}
    f=${CAT_FAIL[$cat]:-0}
    total=$(( p + f ))
    if [ "$cat" = "ok/extras" ]; then
        status="bonus"
    elif [ "$f" -eq 0 ] && [ "$total" -gt 0 ]; then
        status="PASS"
    else
        status="FAIL"
        ALL_GREEN=false
    fi
    printf "%-25s %d/%d [%s]\n" "$cat" "$p" "$total" "$status"
done

echo ""
if $ALL_GREEN; then
    echo "✅ All required tests pass. Ready for review."
    exit 0
else
    echo "❌ Some required tests failed. Fix and re-run."
    exit 1
fi
```

- [ ] **Step 2: Make executable and commit**

```bash
chmod +x tests/hulk/run_tests.sh
git add tests/hulk/run_tests.sh
git commit -m "feat(grading): add local test runner script"
```

---

## Task 9: GitHub Actions Workflow

**Files:**
- Create: `.github/workflows/grade.yml`

- [ ] **Step 1: Write grade.yml**

```yaml
name: HULK Grading

on:
  issues:
    types: [opened, labeled]
  issue_comment:
    types: [created]

permissions:
  issues: write
  contents: read

jobs:
  grade:
    runs-on: ubuntu-latest
    if: |
      (github.event_name == 'issues' &&
       contains(github.event.issue.labels.*.name, 'grading')) ||
      (github.event_name == 'issue_comment' &&
       contains(github.event.issue.body, '') &&
       contains(github.event.issue.labels.*.name, 'grading') &&
       startsWith(github.event.comment.body, '/regrade') &&
       (github.event.comment.author_association == 'OWNER' ||
        github.event.comment.author_association == 'COLLABORATOR' ||
        github.event.comment.author_association == 'MEMBER' ||
        github.event.comment.user.login == github.event.issue.user.login))

    steps:
      - name: Checkout matcom/compilers
        uses: actions/checkout@v4

      - name: Parse issue
        id: parse
        env:
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
        run: |
          ISSUE_NUM=${{ github.event.issue.number }}
          BODY=$(gh issue view "$ISSUE_NUM" --json body --jq '.body')
          REPO_URL=$(echo "$BODY" | grep -oE 'https://github\.com/[a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+' | head -1)
          BRANCH=$(echo "$BODY" | grep -A2 "^### Branch" | grep -v "^###" | grep -v "^$" | head -1 | tr -d ' \r\n')
          [ -z "$BRANCH" ] && BRANCH="main"
          [ -z "$REPO_URL" ] && { echo "ERROR: no repo URL found in issue body" >&2; exit 1; }
          echo "repo_url=$REPO_URL" >> $GITHUB_OUTPUT
          echo "branch=$BRANCH" >> $GITHUB_OUTPUT
          echo "issue_num=$ISSUE_NUM" >> $GITHUB_OUTPUT

      - name: Post "running" comment
        env:
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
        run: |
          gh issue comment ${{ steps.parse.outputs.issue_num }} \
            --body "⏳ **HULK Grading running** on \`${{ steps.parse.outputs.repo_url }}\` @ \`${{ steps.parse.outputs.branch }}\`..."

      - name: Clone student repo
        id: clone
        timeout-minutes: 2
        run: |
          git clone --depth 1 \
            --branch "${{ steps.parse.outputs.branch }}" \
            "${{ steps.parse.outputs.repo_url }}" \
            /tmp/student_repo
          echo "done=true" >> $GITHUB_OUTPUT

      - name: Build
        id: build
        timeout-minutes: 8
        working-directory: /tmp/student_repo
        run: |
          make build 2>&1 | tee /tmp/build.log
          if [ ! -f "./hulk" ]; then
            echo "BUILD_FAILED: ./hulk not found after make build" >> /tmp/build.log
            exit 1
          fi

      - name: Check REPORT.md
        id: report
        working-directory: /tmp/student_repo
        run: |
          if [ -f REPORT.md ]; then
            WORDS=$(wc -w < REPORT.md)
            echo "exists=true" >> $GITHUB_OUTPUT
            echo "words=$WORDS" >> $GITHUB_OUTPUT
          else
            echo "exists=false" >> $GITHUB_OUTPUT
            echo "words=0" >> $GITHUB_OUTPUT
          fi

      - name: Run tests
        id: tests
        if: steps.build.outcome == 'success'
        working-directory: /tmp/student_repo
        run: |
          set +e
          bash "$GITHUB_WORKSPACE/tests/hulk/run_tests.sh" \
            /tmp/student_repo \
            "$GITHUB_WORKSPACE/tests/hulk" \
            2>&1 | tee /tmp/test_results.txt
          echo "exit_code=$?" >> $GITHUB_OUTPUT

      - name: Post results
        if: always()
        env:
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
        run: |
          python3 "$GITHUB_WORKSPACE/tests/hulk/format_comment.py" \
            --build "${{ steps.build.outcome }}" \
            --build-log /tmp/build.log \
            --report-exists "${{ steps.report.outputs.exists }}" \
            --report-words "${{ steps.report.outputs.words }}" \
            --test-results /tmp/test_results.txt \
            --repo "${{ steps.parse.outputs.repo_url }}" \
            > /tmp/comment.md || true
          gh issue comment ${{ steps.parse.outputs.issue_num }} \
            --body "$(cat /tmp/comment.md)"
```

- [ ] **Step 2: Commit**

```bash
git add .github/workflows/grade.yml
git commit -m "feat(grading): add CI grading workflow"
```

---

## Task 10: Comment Formatter

**Files:**
- Create: `tests/hulk/format_comment.py`

- [ ] **Step 1: Write format_comment.py**

```python
#!/usr/bin/env python3
"""Format grading run results into a GitHub issue comment (Markdown)."""
import argparse, re, sys
from datetime import datetime, timezone

def parse_test_results(path):
    """Parse run_tests.sh output into category stats."""
    cats = {}
    failures = []
    try:
        with open(path) as f:
            for line in f:
                m = re.match(r'(PASS|FAIL) (\S+)/(\S+)(?:: (.+))?', line.strip())
                if m:
                    status, cat, name, reason = m.groups()
                    key = cat
                    if key not in cats:
                        cats[key] = {'pass': 0, 'fail': 0}
                    if status == 'PASS':
                        cats[key]['pass'] += 1
                    else:
                        cats[key]['fail'] += 1
                        failures.append(f'`{cat}/{name}`: {reason or ""}')
    except FileNotFoundError:
        pass
    return cats, failures

def main():
    p = argparse.ArgumentParser()
    p.add_argument('--build', default='unknown')
    p.add_argument('--build-log', default='/dev/null')
    p.add_argument('--report-exists', default='false')
    p.add_argument('--report-words', default='0')
    p.add_argument('--test-results', default='/dev/null')
    p.add_argument('--repo', default='')
    args = p.parse_args()

    now = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
    lines = [f'## 🤖 HULK Grading Report — {now}', '']

    # Build
    if args.build == 'success':
        lines += ['### 📦 Build', '✅ Build successful', '']
    else:
        lines += ['### 📦 Build', '❌ Build failed', '']
        try:
            with open(args.build_log) as f:
                log_tail = f.readlines()[-20:]
            lines += ['```', ''.join(log_tail).strip(), '```', '']
        except Exception:
            pass
        lines += ['> Fix build errors and comment `/regrade` to re-run.', '']
        print('\n'.join(lines))
        return

    # Report
    words = int(args.report_words or 0)
    if args.report_exists == 'true' and words >= 2000:
        lines += ['### 📄 Report', f'✅ REPORT.md found ({words:,} words)', '']
    elif args.report_exists == 'true':
        lines += ['### 📄 Report', f'⚠️ REPORT.md found but only {words} words (minimum 2000)', '']
    else:
        lines += ['### 📄 Report', '❌ REPORT.md not found in repo root', '']

    # Tests
    cats, failures = parse_test_results(args.test_results)
    required = ['ok/minimal', 'ok/types', 'ok/oop', 'errors/lexical', 'errors/syntactic', 'errors/semantic']
    all_green = True

    lines += ['### 🧪 Tests', '', '| Category | Passed | Total | Status |', '|----------|--------|-------|--------|']
    for cat in required + ['ok/extras']:
        d = cats.get(cat, {'pass': 0, 'fail': 0})
        passed, failed = d['pass'], d['fail']
        total = passed + failed
        if cat == 'ok/extras':
            icon = '➖'
        elif failed == 0 and total > 0:
            icon = '✅'
        else:
            icon = '⚠️'
            all_green = False
        lines.append(f'| `{cat}` | {passed} | {total} | {icon} |')
    lines.append('')

    if failures:
        lines += ['### ❌ Failures', '']
        for f in failures:
            lines.append(f'- {f}')
        lines.append('')

    # Verdict
    report_ok = args.report_exists == 'true' and words >= 2000
    if all_green and report_ok:
        lines += ['### 🔖 Status', '', '**✅ Ready for review.** All required tests pass.']
    else:
        lines += ['### 🔖 Status', '', '**❌ Not ready for review.** Fix the issues above and comment `/regrade` to re-run.']

    print('\n'.join(lines))

if __name__ == '__main__':
    main()
```

- [ ] **Step 2: Commit**

```bash
git add tests/hulk/format_comment.py
git commit -m "feat(grading): add comment formatter script"
```

---

## Task 11: Push to matcom/compilers

- [ ] **Step 1: Push all commits**

```bash
git push origin main
```

- [ ] **Step 2: Verify on GitHub**

Check that:
- `.github/ISSUE_TEMPLATE/grading.yml` appears when creating a new issue
- `.github/workflows/grade.yml` appears in Actions tab

---

## Task 12: Smoke Test with michellviu

The smoke test verifies the local runner works. michellviu's compiler uses `cargo build` + `cargo run`, not `./hulk`. Create a thin adapter.

- [ ] **Step 1: Check LLVM/Rust availability on VPS**

```bash
rustc --version && llvm-config --version
```

Expected: Rust and LLVM 18 available. If not:
```bash
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y
source "$HOME/.cargo/env"
# LLVM 18 required for inkwell — install if missing:
# apt-get install -y llvm-18-dev libclang-18-dev clang-18
```

- [ ] **Step 2: Build michellviu's compiler**

```bash
cd /home/apiad/Workspace/repos/matcom/compilers-2026/michellviu
cargo build 2>&1 | tail -5
```

- [ ] **Step 3: Create ./hulk adapter**

michellviu's binary is `target/debug/hulk_compiler`. The contract requires `./hulk`. Create a wrapper:

```bash
cat > /home/apiad/Workspace/repos/matcom/compilers-2026/michellviu/hulk << 'EOF'
#!/bin/bash
# Adapter: wraps cargo-built binary to satisfy ./hulk <file> interface
DIR="$(cd "$(dirname "$0")" && pwd)"
exec "$DIR/target/debug/hulk_compiler" "$@"
EOF
chmod +x /home/apiad/Workspace/repos/matcom/compilers-2026/michellviu/hulk
```

- [ ] **Step 4: Run the test suite against michellviu**

```bash
bash /home/apiad/Workspace/repos/matcom/compilers/tests/hulk/run_tests.sh \
    /home/apiad/Workspace/repos/matcom/compilers-2026/michellviu \
    /home/apiad/Workspace/repos/matcom/compilers/tests/hulk
```

- [ ] **Step 5: Review results and fix any test issues**

Expected: ok/minimal ✅, ok/types ✅, ok/oop ✅, errors/* mostly ✅.
Any failures → investigate: is it a test bug (wrong expected output) or a real compiler issue?
Fix test files if needed, commit.
