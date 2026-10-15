#!/usr/bin/env python3
"""Install self-contained Cadence skills without Cadence, network or symlinks."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile

SKILLS = ('allegro-padstack', 'allegro-package', 'allegro-library', 'orcad-symbol', 'allegro-pcb', 'orcad-schematic')
HOSTS = {'codex': '.codex', 'claude': '.claude', 'agents': '.agents'}

def inventory(root):
    if root.is_symlink():
        raise ValueError('Symlinked skill: ' + str(root))
    result = {}
    for p in sorted(root.rglob('*')):
        if p.is_symlink():
            raise ValueError('Symlink inside skill: ' + str(p))
        if p.is_file():
            result[p.relative_to(root).as_posix()] = {
                'size': p.stat().st_size,
                'sha256': hashlib.sha256(p.read_bytes()).hexdigest()}
    if 'SKILL.md' not in result:
        raise ValueError('Skill entrypoint missing: ' + str(root))
    return result

def payload(source, name):
    manifest = json.loads((source.parent / 'scripts' / 'skill-files.json').read_text(encoding='utf-8'))
    result = {}
    for relative in manifest[name]:
        rel = Path(relative)
        if rel.is_absolute() or '..' in rel.parts:
            raise ValueError('Invalid distribution path')
        path = source / name / rel
        if any(p.is_symlink() for p in (path, *path.parents)):
            raise ValueError('Symlink in distribution source')
        result[relative] = {'size': path.stat().st_size, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    if 'SKILL.md' not in result: raise ValueError('Missing skill entrypoint')
    return result

def install(source, home, hosts, replace=False, dry_run=False, codex_home=None):
    # Full preflight before any destination changes.
    plans = []
    destinations = set()
    for name in SKILLS:
        src = source / name
        expected = payload(source, name)
        for host in hosts:
            base = codex_home if host == 'codex' and codex_home else home / HOSTS[host]
            dst = base / 'skills' / name
            # Resolve directory aliases, but preserve the leaf: replacing a
            # skill symlink moves the link itself, never its target.
            destination = dst.parent.resolve() / dst.name
            if destination == src.resolve():
                raise ValueError('Source and destination must be different')
            if destination in destinations:
                continue
            exists = dst.exists() or dst.is_symlink()
            same = False
            if exists and dst.is_dir():
                try: same = inventory(dst) == expected
                except ValueError: pass
            action = 'unchanged' if same else ('replace' if exists else 'install')
            if exists and not same and not replace:
                raise ValueError('Different skill already exists; use --replace to back it up: ' + str(dst))
            plans.append((name, src, dst, expected, action, base))
            destinations.add(destination)
    result = []
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    for name, src, dst, expected, action, base in plans:
        row = {'skill': name, 'destination': str(dst), 'action': action, 'files': len(expected)}
        if dry_run:
            row['verified'] = False
        elif action == 'unchanged':
            row['verified'] = True
        else:
            dst.parent.mkdir(parents=True, exist_ok=True)
            stage = Path(tempfile.mkdtemp(prefix='.' + name + '-', dir=dst.parent))
            backup = None
            moved = False
            try:
                for relative in expected:
                    target = stage / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src / relative, target)
                if inventory(stage) != expected:
                    raise ValueError('Staged file inventory mismatch')
                if action == 'replace':
                    backup = base / 'skill-backups' / stamp / name
                    backup.parent.mkdir(parents=True, exist_ok=True)
                    dst.rename(backup)
                stage.rename(dst)
                moved = True
                if inventory(dst) != expected:
                    raise ValueError('Installed file inventory mismatch')
                row['verified'] = True
                if backup: row['backup'] = str(backup)
            except Exception:
                if moved: shutil.rmtree(dst)
                if backup and (backup.exists() or backup.is_symlink()): backup.rename(dst)
                raise
            finally:
                if stage.exists(): shutil.rmtree(stage)
        result.append(row)
    return {'status': 'dry_run' if dry_run else 'verified', 'skills': result}

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--home', type=Path, help='Target user home; default current user')
    p.add_argument('--host', choices=tuple(HOSTS) + ('all',), default='all')
    p.add_argument('--codex-home', type=Path, help='Override CODEX_HOME')
    p.add_argument('--replace', action='store_true', help='Back up and replace differing skills')
    p.add_argument('--dry-run', action='store_true')
    a = p.parse_args()
    try:
        source = Path(__file__).resolve().parents[1] / 'skills'
        home = (a.home or Path.home()).expanduser().absolute()
        configured = a.codex_home or (os.environ.get('CODEX_HOME') if a.home is None else None)
        ch = Path(configured).expanduser().absolute() if configured else None
        hosts = tuple(HOSTS) if a.host == 'all' else (a.host,)
        print(json.dumps(install(source, home, hosts, a.replace, a.dry_run, ch), ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError) as e:
        print(json.dumps({'status': 'failed', 'error': str(e)}, ensure_ascii=False), file=sys.stderr)
        return 1

if __name__ == '__main__':
    sys.exit(main())
