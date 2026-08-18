#!/usr/bin/env python3
"""
迁移脚本：将现有任务文件重命名为 {task_id}_{title_slug}.md 格式
并更新所有 [[path]] 引用。

用法：
    python3 shared/toolkit/kanban/migrate_filenames.py [--dry-run]
"""

import os
import re
import sys
import importlib.util
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_HERE = Path(__file__).resolve().parent
_SCAN_DOCS_SPEC = importlib.util.spec_from_file_location('kanban_scan_docs', _HERE / 'scan-docs.py')
scan_docs = importlib.util.module_from_spec(_SCAN_DOCS_SPEC)
_SCAN_DOCS_SPEC.loader.exec_module(scan_docs)
CONFIG = scan_docs.load_config()
SCAN_DIRS = CONFIG.get('scan_dirs', scan_docs._DEFAULTS['scan_dirs'])
SKIP_PATTERNS = CONFIG.get('skip_patterns', [])


def title_to_slug(title):
    """与 scan-docs.py 中 _title_to_slug 保持一致"""
    return scan_docs._title_to_slug(title)


def build_filename(task_id, title):
    slug = title_to_slug(title)
    return f"{task_id}_{slug}.md"


def extract_frontmatter(content):
    fm, _ = scan_docs.extract_frontmatter(content)
    return fm


def parse_frontmatter(fm_text):
    """解析 frontmatter 文本为 dict"""
    return fm_text if isinstance(fm_text, dict) else {}


def scan_task_files():
    """扫描所有任务文件，返回 [(rel_path, frontmatter_dict)]"""
    tasks = []
    for scan_dir in SCAN_DIRS:
        base = REPO_ROOT / scan_dir
        if not base.exists():
            continue
        for fpath in sorted(base.rglob('*.md')):
            if SKIP_PATTERNS and scan_docs._should_skip(fpath, SKIP_PATTERNS):
                continue
            try:
                content = fpath.read_text(encoding='utf-8')
            except Exception:
                continue
            fm_text = extract_frontmatter(content)
            if not fm_text:
                continue
            # 跳过模板文件
            if '{' in content[:200]:
                continue
            fm = parse_frontmatter(fm_text)
            rel_path = str(fpath.relative_to(REPO_ROOT))
            tasks.append((rel_path, fm))
    return tasks


def update_all_references(old_path, new_path, dry_run=False):
    """扫描所有 .md 文件，替换 [[old_path]] → [[new_path]]"""
    old_pattern = f'[[{old_path}]]'
    new_pattern = f'[[{new_path}]]'
    updated = []
    for scan_dir in SCAN_DIRS:
        base = REPO_ROOT / scan_dir
        if not base.exists():
            continue
        for fpath in base.rglob('*.md'):
            if SKIP_PATTERNS and scan_docs._should_skip(fpath, SKIP_PATTERNS):
                continue
            try:
                content = fpath.read_text(encoding='utf-8')
            except Exception:
                continue
            if old_pattern not in content:
                continue
            if not dry_run:
                new_content = content.replace(old_pattern, new_pattern)
                fpath.write_text(new_content, encoding='utf-8')
            updated.append(str(fpath.relative_to(REPO_ROOT)))
    return updated


def migrate(dry_run=False):
    tasks = scan_task_files()
    renamed_count = 0
    ref_updated_count = 0
    skipped_count = 0
    errors = []

    # 第一步：重命名文件
    rename_map = {}  # old_path -> new_path
    for rel_path, fm in tasks:
        task_id = fm.get('task_id', '')
        title = fm.get('title', '')
        if not task_id or not title:
            skipped_count += 1
            print(f"  跳过（无 task_id 或 title）: {rel_path}")
            continue

        # 检查文件名是否已经是新格式
        current_filename = Path(rel_path).name
        expected_filename = build_filename(task_id, title)
        if current_filename == expected_filename:
            skipped_count += 1
            continue

        # 检查文件名是否以 task_id_ 开头（可能 title 变了但格式已经对）
        if current_filename.startswith(f"{task_id}_"):
            # title 可能已变更，需要更新文件名
            pass

        old_abs = REPO_ROOT / rel_path
        new_rel_path = str(Path(rel_path).parent / expected_filename)
        new_abs = REPO_ROOT / new_rel_path

        if new_abs.exists() and old_abs != new_abs:
            errors.append(f"目标文件已存在: {new_rel_path}")
            print(f"  错误: 目标文件已存在 {new_rel_path}")
            continue

        print(f"  {'[dry-run] ' if dry_run else ''}{rel_path}")
        print(f"    → {new_rel_path}")
        rename_map[rel_path] = new_rel_path

        if not dry_run:
            new_abs.parent.mkdir(parents=True, exist_ok=True)
            old_abs.rename(new_abs)

        renamed_count += 1

    # 第二步：更新所有引用
    if rename_map:
        print(f"\n更新引用:")
        for old_path, new_path in rename_map.items():
            updated = update_all_references(old_path, new_path, dry_run)
            if updated:
                ref_updated_count += len(updated)
                for ref_file in updated:
                    print(f"  {'[dry-run] ' if dry_run else ''}{ref_file}: [[{old_path}]] → [[{new_path}]]")

    # 汇总
    print(f"\n{'[dry-run] ' if dry_run else ''}迁移完成:")
    print(f"  重命名文件: {renamed_count}")
    print(f"  更新引用: {ref_updated_count}")
    print(f"  跳过（已是新格式或无 task_id）: {skipped_count}")
    if errors:
        print(f"  错误: {len(errors)}")
        for e in errors:
            print(f"    - {e}")


if __name__ == '__main__':
    dry_run = '--dry-run' in sys.argv
    if dry_run:
        print("=== DRY RUN 模式（不会实际修改文件）===\n")
    print("扫描任务文件...\n")
    migrate(dry_run)
