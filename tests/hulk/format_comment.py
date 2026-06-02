#!/usr/bin/env python3
"""Format run_tests.sh output into a GitHub issue Markdown comment."""
import argparse
import re
import sys
from datetime import datetime, timezone


def strip_ansi(text: str) -> str:
    return re.sub(r'\x1b\[[0-9;]*m', '', text)


def parse_results(path: str):
    """
    Returns (cats, failures, all_pass).
    cats: {category: {'pass': N, 'fail': N}}
    failures: list of (cat/name, reason) strings
    all_pass: bool from RESULT line
    """
    cats: dict = {}
    failures: list = []
    all_pass = False
    in_failures = False
    try:
        with open(path) as f:
            for raw in f:
                line = strip_ansi(raw.strip())
                if not line:
                    continue
                if line.startswith('RESULT: ALL_PASS'):
                    all_pass = True
                    in_failures = False
                    continue
                if line.startswith('RESULT: FAIL'):
                    in_failures = False
                    continue
                if line.startswith('FAILURES:'):
                    in_failures = True
                    rest = line[len('FAILURES:'):].strip()
                    if rest:
                        failures.append(rest.lstrip('- '))
                    continue
                if in_failures and line.startswith('-'):
                    failures.append(line.lstrip('- '))
                    continue
                m = re.match(r'^(PASS|FAIL)\s+(\S+)/(\S+)(?::\s*(.+))?$', line)
                if m:
                    status, cat, name, reason = m.groups()
                    if cat not in cats:
                        cats[cat] = {'pass': 0, 'fail': 0}
                    if status == 'PASS':
                        cats[cat]['pass'] += 1
                    else:
                        cats[cat]['fail'] += 1
                        if reason:
                            failures.append(f'`{cat}/{name}`: {reason}')
    except FileNotFoundError:
        pass
    return cats, failures, all_pass


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
    out = [f'## 🤖 HULK Grading Report — {now}', '']
    if args.repo:
        out += [f'> Repo: `{args.repo}`', '']

    # ── Build ──────────────────────────────────────────────────────────────
    if args.build == 'success':
        out += ['### 📦 Build', '✅ Build successful', '']
    else:
        out += ['### 📦 Build', '❌ Build failed', '']
        try:
            with open(args.build_log) as f:
                tail = ''.join(f.readlines()[-25:]).strip()
            out += ['<details><summary>Build log (last 25 lines)</summary>', '',
                    '```', tail, '```', '</details>', '']
        except Exception:
            pass
        out += ['> Fix build errors and comment `/regrade` to re-run.']
        print('\n'.join(out))
        return

    # ── Report ─────────────────────────────────────────────────────────────
    words = int(args.report_words or 0)
    if args.report_exists == 'true' and words >= 2000:
        out += ['### 📄 Report', f'✅ `REPORT.md` found ({words:,} words)', '']
    elif args.report_exists == 'true':
        out += ['### 📄 Report',
                f'⚠️ `REPORT.md` found but only **{words} words** (minimum 2000). '
                'Add more documentation and comment `/regrade`.',
                '']
    else:
        out += ['### 📄 Report',
                '❌ `REPORT.md` not found in repo root.',
                '']

    # ── Tests ──────────────────────────────────────────────────────────────
    cats, failures, all_pass = parse_results(args.test_results)

    required = [
        'ok/minimal', 'ok/types', 'ok/oop',
        'errors/lexical', 'errors/syntactic', 'errors/semantic',
    ]
    all_required_green = True

    out += ['### 🧪 Tests', '',
            '| Category | Passed | Total | Status |',
            '|----------|--------|-------|--------|']

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
            all_required_green = False
        out.append(f'| `{cat}` | {passed} | {total} | {icon} |')

    out.append('')

    if failures:
        out += ['### ❌ Failures', '']
        for f in failures[:20]:  # cap at 20 to avoid giant comments
            out.append(f'- {f}')
        if len(failures) > 20:
            out.append(f'- *(and {len(failures) - 20} more…)*')
        out.append('')

    # ── Verdict ────────────────────────────────────────────────────────────
    report_ok = args.report_exists == 'true' and words >= 2000
    ready = all_required_green and report_ok

    out += ['### 🔖 Status', '']
    if ready:
        out.append('**✅ Ready for review.** All required tests pass and `REPORT.md` is present.')
    else:
        issues = []
        if not all_required_green:
            issues.append('some required tests are failing')
        if not report_ok:
            issues.append('`REPORT.md` is missing or too short')
        out.append(f'**❌ Not ready for review** ({"; ".join(issues)}).')
        out.append('Fix the issues above and comment `/regrade` to re-run.')

    print('\n'.join(out))


if __name__ == '__main__':
    main()
