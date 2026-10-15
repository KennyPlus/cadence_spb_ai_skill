#!/usr/bin/env python3
"""Prepare an audited job-local SPB24 csh launcher; never edit the installation."""
import argparse
import hashlib
import json
import shlex
from pathlib import Path


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--cadence-root', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    a = p.parse_args()
    root = a.cadence_root.resolve(strict=True)
    source = root / 'tools.lnx86/bin/wstarter'
    data = source.read_text()
    # Refuse an unknown launcher instead of silently producing an untested rewrite.
    if data.count('`cds_root $0`') != 1 or 'if ($? == 0)' not in data:
        p.error('Unrecognized launcher: inspect the current installation before adapting it')
    libs = ['/usr/lib/x86_64-linux-gnu/libGL.so.1', '/usr/lib/x86_64-linux-gnu/libXext.so.6']
    if not all(Path(x).is_file() for x in libs):
        p.error('Expected host GL/Xext libraries are missing')
    data = data.replace('if ($? == 0)', 'if ($status == 0)')
    data = data.replace('`cds_root $0`', '`cds_root ' + shlex.quote(str(source)) + '`')
    if data.count('# Local variables') != 1:
        p.error('Unrecognized launcher variable section')
    data = data.replace('# Local variables', '# Local variables\nset _opengllib = ' + libs[0] + '\nset _xextlib = ' + libs[1])
    out = a.out.resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open('x') as f:
        f.write(data)
    out.chmod(0o755)
    print(json.dumps({'source': str(source), 'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
                      'starter': str(out), 'starter_sha256': hashlib.sha256(out.read_bytes()).hexdigest()}, indent=2))

if __name__ == '__main__':
    main()
