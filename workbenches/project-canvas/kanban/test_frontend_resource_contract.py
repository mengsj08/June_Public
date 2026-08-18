#!/usr/bin/env python3
"""Static frontend resource contracts for the kanban entry page."""

import re
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit


_HERE = Path(__file__).resolve().parent
_KANBAN_HTML = _HERE / 'kanban.html'
_MAIN_JS = _HERE / 'static' / 'kanban' / 'main.js'
_STATIC_IMPORT_RE = re.compile(
    r'^\s*(?:import|export)\s+(?:[\s\S]*?\s+from\s+)?[\'\"]([^\'\"]+)[\'\"]\s*;',
    re.MULTILINE,
)


class _LocalResourceParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.references = []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == 'script' and values.get('src'):
            self.references.append(values['src'])
        if tag == 'link' and values.get('href'):
            self.references.append(values['href'])


def _without_query_or_fragment(reference):
    parts = urlsplit(reference)
    return parts.path


def _resolve_js_import(importer, reference):
    path = _without_query_or_fragment(reference)
    assert path.startswith(('./', '../')), (
        f'{importer.relative_to(_HERE)} uses a non-relative static import: {reference}'
    )
    return (importer.parent / path).resolve()


def _resolve_html_resource(reference):
    path = _without_query_or_fragment(reference)
    if not path or reference.startswith(('http://', 'https://', '//', 'data:')):
        return None
    if path.startswith('/'):
        return (_HERE / path.lstrip('/')).resolve()
    return (_KANBAN_HTML.parent / path).resolve()


def test_main_static_module_graph_exists_inside_kanban_tree():
    pending = [_MAIN_JS]
    visited = set()
    missing = []
    edge_count = 0
    while pending:
        importer = pending.pop()
        if importer in visited:
            continue
        visited.add(importer)
        source = importer.read_text(encoding='utf-8')
        for reference in _STATIC_IMPORT_RE.findall(source):
            edge_count += 1
            target = _resolve_js_import(importer, reference)
            assert target == _HERE or _HERE in target.parents, (
                f'{importer.relative_to(_HERE)} import escapes the kanban tree: {reference}'
            )
            if not target.is_file():
                missing.append(
                    f'{importer.relative_to(_HERE)}: {reference} -> {target.relative_to(_HERE)}'
                )
                continue
            pending.append(target)

    assert edge_count, 'main.js must keep at least one statically checkable module import'
    assert not missing, 'missing static module imports:\n' + '\n'.join(missing)


def test_kanban_html_local_script_and_stylesheet_resources_exist():
    parser = _LocalResourceParser()
    parser.feed(_KANBAN_HTML.read_text(encoding='utf-8'))

    local_resources = []
    missing = []
    for reference in parser.references:
        target = _resolve_html_resource(reference)
        if target is None:
            continue
        local_resources.append(reference)
        assert target == _HERE or _HERE in target.parents, (
            f'kanban.html resource escapes the kanban tree: {reference}'
        )
        if not target.is_file():
            missing.append(f'{reference} -> {target.relative_to(_HERE)}')

    assert local_resources, 'kanban.html must keep local script or stylesheet resources'
    assert not missing, 'missing kanban.html local resources:\n' + '\n'.join(missing)
