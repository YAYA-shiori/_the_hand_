#!/usr/bin/env python3
"""
release_ghost.py - Ukagaka ghost release tooling

Subcommands:
  dau  Generate updates2.dau
         Spec: https://ssp.shillest.net/ukadoc/manual/spec_update_file.html
  nar  Create .nar archive (ZIP with .nar extension)

Usage:
  python release_ghost.py dau [--root DIR] [--output PATH]
  python release_ghost.py nar [--root DIR] [--output PATH]

Defaults:
  --root    current directory
  --output  <root>/updates2.dau  (dau)
            <root>/<dirname>.nar (nar)

Ignore files (gitignore syntax):
  .updateignore  patterns excluded from updates2.dau
  .narignore     patterns excluded from .nar archive
"""

import argparse
import fnmatch
import hashlib
import subprocess
import zipfile
from pathlib import Path


# ── .???ignore パターン ──────────────────────────────────────────────────────

def _load_ignore_patterns(path: Path) -> list[str]:
    """Load patterns from a .updateignore/.narignore file (gitignore syntax)."""
    if not path.exists():
        return []
    patterns = []
    for line in path.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if line and not line.startswith('#'):
            patterns.append(line)
    return patterns


def _is_ignored(rel_str: str, patterns: list[str]) -> bool:
    """Check if a relative path (forward-slash separated) matches any ignore pattern."""
    parts = rel_str.split('/')
    basename = parts[-1]
    for pattern in patterns:
        if pattern.endswith('/'):
            # Directory pattern: match if any ancestor component matches
            dir_pat = pattern.rstrip('/')
            if any(fnmatch.fnmatch(p, dir_pat) for p in parts[:-1]):
                return True
        elif '/' in pattern:
            # Anchored path pattern (contains slash)
            if fnmatch.fnmatch(rel_str, pattern.lstrip('/')):
                return True
        else:
            # Filename pattern: match against basename
            if fnmatch.fnmatch(basename, pattern):
                return True
    return False


# ── ファイル列挙 ─────────────────────────────────────────────────────────────

def collect_files(root: Path, ignore_patterns: list[str]) -> list[tuple[str, Path]]:
    """ゴースト配布対象ファイルの一覧を返す。

    `git ls-files` を使うことで .gitignore の除外設定を自動的に尊重する。
    git が使えない環境ではディレクトリ走査にフォールバックする。

    Returns:
        [(フォワードスラッシュ区切り相対パス, 絶対パス), ...] のソート済みリスト
    """
    try:
        result = subprocess.run(
            ['git', 'ls-files', '--cached', '--others', '--exclude-standard'],
            cwd=root,
            capture_output=True,
            text=True,
            check=True,
        )
        raw_paths = [p.strip() for p in result.stdout.splitlines() if p.strip()]
    except (subprocess.CalledProcessError, FileNotFoundError):
        raw_paths = [
            '/'.join(p.relative_to(root).parts)
            for p in root.rglob('*')
            if p.is_file()
        ]

    results = []
    for rel_str in raw_paths:
        rel_str = rel_str.replace('\\', '/')

        # ツール自身は常に除外
        if rel_str == 'release_ghost.py':
            continue

        if _is_ignored(rel_str, ignore_patterns):
            continue

        abs_path = root / Path(*rel_str.split('/'))
        if abs_path.is_file():
            results.append((rel_str, abs_path))

    results.sort(key=lambda x: x[0])
    return results


# ── updates2.dau 生成 ────────────────────────────────────────────────────────

def _md5(path: Path) -> str:
    h = hashlib.md5()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(65536), b''):
            h.update(chunk)
    return h.hexdigest()


def cmd_dau(root: Path, output: Path) -> None:
    """updates2.dau を生成する。"""
    patterns = _load_ignore_patterns(root / '.updateignore')
    patterns.append('updates2.dau')  # 自己参照を避ける
    files = collect_files(root, patterns)

    with open(output, 'wb') as f:
        for i, (rel_str, abs_path) in enumerate(files):
            stat = abs_path.stat()
            fields = [
                rel_str,
                _md5(abs_path),
                f'size={stat.st_size}',
            ]
            if i == 0:
                fields.append('charset=UTF-8')
            f.write(('\x01'.join(fields) + '\r\n').encode('utf-8'))

    print(f'Generated {output} ({len(files)} files)')


# ── .nar アーカイブ生成 ──────────────────────────────────────────────────────

def cmd_nar(root: Path, output: Path) -> None:
    """_the_hand_.nar（中身は ZIP）を生成する。

    updates2.dau は除外対象に含めないので、事前に dau コマンドで
    生成しておくと自動的に同梱される。
    """
    patterns = _load_ignore_patterns(root / '.narignore')
    files = collect_files(root, patterns)

    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as zf:
        for rel_str, abs_path in files:
            zf.write(abs_path, rel_str)
            print(f'  Added: {rel_str}')

    print(f'Created {output} ({len(files)} files)')


# ── CLI ─────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description='Ukagaka ghost release tooling',
    )
    parser.add_argument(
        '--root', type=Path, default=Path('.'),
        metavar='DIR', help='ghost root directory (default: current directory)',
    )
    sub = parser.add_subparsers(dest='command', required=True)

    # dau サブコマンド
    p_dau = sub.add_parser('dau', help='generate updates2.dau')
    p_dau.add_argument(
        '--output', type=Path, default=None,
        metavar='PATH', help='output path (default: <root>/updates2.dau)',
    )

    # nar サブコマンド
    p_nar = sub.add_parser('nar', help='create .nar archive')
    p_nar.add_argument(
        '--output', type=Path, default=None,
        metavar='PATH', help='output path (default: <root>/<dirname>.nar)',
    )

    args = parser.parse_args()
    root = args.root.resolve()

    if args.command == 'dau':
        output = args.output or root / 'updates2.dau'
        cmd_dau(root, output.resolve())

    elif args.command == 'nar':
        output = args.output or (root / (root.name + '.nar'))
        cmd_nar(root, output.resolve())


if __name__ == '__main__':
    main()
