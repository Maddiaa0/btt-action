#!/usr/bin/env python3
"""Turn btt 0.2 text diagnostics into Actions annotations and linked summaries."""
import html
import os
from pathlib import Path
import re
import sys
from urllib.parse import quote


def escape(value, property=False):
    value = str(value).replace('%', '%25').replace('\r', '%0D').replace('\n', '%0A')
    if property:
        value = value.replace(':', '%3A').replace(',', '%2C')
    return value


def report(log):
    workspace = Path(os.environ.get('GITHUB_WORKSPACE', os.getcwd())).resolve()
    cwd = Path.cwd()
    ancestors = [cwd, *cwd.parents]
    root = next((p for p in ancestors if (p / 'btt.toml').is_file()), None)
    if root is None:
        root = next((p for p in ancestors if (p / '.git').exists()), cwd)
    revision = os.environ.get('GITHUB_SHA', '')
    event_path = os.environ.get('GITHUB_EVENT_PATH')
    if event_path:
        import json
        event = json.loads(Path(event_path).read_text())
        revision = event.get('pull_request', {}).get('head', {}).get('sha', revision)
    base = (os.environ.get('GITHUB_SERVER_URL', 'https://github.com') + '/' +
            os.environ.get('GITHUB_REPOSITORY', '') + '/blob/' + quote(revision, safe=''))

    def relative(path):
        try:
            return (root / path).resolve().relative_to(workspace).as_posix()
        except ValueError:
            return None

    def url(path, line=1):
        rel = relative(path)
        if rel is None or not revision or not os.environ.get('GITHUB_REPOSITORY'):
            return None
        return base + '/' + quote(rel, safe='/') + '#L' + str(line)

    def link(path, line=1):
        label = html.escape(relative(path) or str(path))
        target = url(path, line)
        if target:
            return f'<a href="{html.escape(target, quote=True)}">{label}:{line}</a>'
        return label

    rows = []
    tree = target = None
    details = []

    def emit():
        if tree is None:
            return
        for level, message in details:
            line = 1
            location = re.search(r'\(' + re.escape(tree) + r':(\d+)\)$', message)
            grammar = re.search(r': line (\d+):', message)
            if location or grammar:
                line = int((location or grammar).group(1))
            test_line = 1
            if target:
                match = re.search(r'\(' + re.escape(target) + r':(\d+)\)$', message)
                if match:
                    test_line = int(match.group(1))
            text = message
            if target:
                text += '\nTest: ' + (url(target, test_line) or target)
            rel = relative(tree)
            properties = 'title=BTT'
            if rel:
                properties += f',file={escape(rel, True)},line={line}'
            print(f'::{level} {properties}::{escape(text)}')
            rows.append(f'<tr><td>{level}</td><td>{link(tree, line)}</td>'
                        f'<td>{link(target, test_line) if target else "No test target reported"}</td>'
                        f'<td>{html.escape(message)}</td></tr>')

    for raw in log.splitlines():
        header = re.match(r'^[✗!] (.+)$', raw)
        if header:
            emit()
            body = header.group(1)
            tree, arrow, target = body.partition(' → ')
            tree, separator, reason = tree.partition(' — ')
            target = target if arrow else None
            details = []
            if not target and tree.endswith('.tree'):
                stem = (root / tree).with_suffix('')
                candidates = [Path(str(stem) + suffix) for suffix in
                              ('.test.ts', '.spec.ts', '.test.tsx', '.test.mts', '.test.js', '.spec.js', '.rs')]
                target = next((str(p) for p in candidates if p.is_file()), None)
            if separator:
                details.append(('warning' if raw.startswith('!') else 'error', reason))
        elif raw.startswith('✓ '):
            emit()
            tree = target = None
            details = []
        else:
            diagnostic = re.match(r'^    (error|warn)\s+(.*)$', raw)
            if diagnostic and tree:
                details.append(('warning' if diagnostic[1] == 'warn' else 'error', diagnostic[2]))
    emit()
    summary = os.environ.get('GITHUB_STEP_SUMMARY')
    if summary:
        with open(summary, 'a') as output:
            output.write('### BTT test specifications\n\n')
            if rows:
                output.write('<table><tr><th>Severity</th><th>Specification</th><th>Test</th><th>Finding</th></tr>\n')
                output.write('\n'.join(rows) + '\n</table>\n\n')
            output.write('<details><summary>Full BTT output</summary><pre>')
            output.write(html.escape(log))
            output.write('</pre></details>\n')


if __name__ == '__main__':
    report(Path(sys.argv[1]).read_text())
