#!/usr/bin/env python3
"""Reject local IP literals in repository text; never contact any host."""
import argparse
import ipaddress
import os
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
IPV4 = re.compile(r"(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?![\w.])")
IPV6 = re.compile(r"(?<![\w:])[\da-fA-F]*:[\da-fA-F:.]+(?:%[\w.-]+)?(?![\w:.%$\[])")


def local_addresses(text):
    for pattern in (IPV4, IPV6):
        for match in pattern.finditer(text):
            try:
                address = ipaddress.ip_address(match.group())
            except ValueError:
                continue
            mapped = getattr(address, 'ipv4_mapped', None)
            address = mapped or address
            if (address.is_private or address.is_loopback or
                    address.is_link_local or address.is_unspecified):
                yield match.start()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--all-local', action='store_true',
                        help='Include ignored files, excluding Git metadata and bytecode')
    args = parser.parse_args()
    if args.all_local or not (ROOT / '.git').exists():
        paths = []
        for directory, dirs, files in os.walk(ROOT, followlinks=False):
            dirs[:] = [d for d in dirs if d not in ('.git', '__pycache__')]
            paths.extend(Path(directory) / name for name in files)
    else:
        result = subprocess.run(['git', 'ls-files', '-z'], cwd=ROOT,
                                check=True, capture_output=True)
        paths = [ROOT / os.fsdecode(name) for name in result.stdout.split(b'\0') if name]
    failures = 0
    checked = 0
    for path in sorted(paths):
        if path.is_symlink() or not path.is_file():
            continue
        data = path.read_bytes()
        if b'\0' in data:
            continue
        text = data.decode('utf-8', errors='replace')
        checked += 1
        for line, content in enumerate(text.splitlines(), 1):
            if any(True for _ in local_addresses(content)):
                print(f'{path.relative_to(ROOT)}:{line}: local IP literal')
                failures += 1
    print(f'Checked {checked} text files; {failures} offending lines.')
    return bool(failures)


if __name__ == '__main__':
    raise SystemExit(main())
