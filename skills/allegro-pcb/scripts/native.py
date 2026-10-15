"""Explicit native operations on fresh job copies; never edit input designs."""
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import time

from formats import digest, read_netlist, read_placement, require, verify_placement, verify_connectivity


def inventory(directory):
    return {p.relative_to(directory).as_posix(): digest(p)
            for p in sorted(Path(directory).rglob('*')) if p.is_file() and p.name != 'result.json'}


def stage(source, destination, sources):
    source = Path(source).resolve(strict=True)
    require(source.is_file(), 'Expected a regular input file: ' + str(source))
    value = digest(source)
    require(not destination.exists(), 'Staged file already exists: ' + str(destination))
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, destination)
    require(digest(destination) == value, 'Staged file readback failed')
    sources[str(source)] = value


def kill_process_tree(process):
    if os.name == 'nt':
        subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def load_environment(env_file=None, timeout=15):
    """Source an explicit Bash setup script without changing the parent shell."""
    if env_file is None:
        return dict(os.environ), {}
    require(os.name != 'nt', '--env-file requires Bash on POSIX; on Windows initialize the calling shell first')
    path = Path(env_file).resolve(strict=True)
    require(path.is_file(), 'Expected an environment script file')
    before = digest(path)
    bash, env_command = shutil.which('bash'), shutil.which('env')
    require(bash and env_command, 'Environment loading requires bash and env')
    require(timeout > 0, 'Environment timeout must be positive')
    # Keep filenames as argv, not interpolated shell code. Source banners go
    # to stderr, and the NUL-delimited environment stays in memory only.
    process = subprocess.Popen(
        [bash, '--noprofile', '--norc', '-c', 'source "$1" >&2 || exit $?; command "$2" -0',
         'cadence-env', str(path), env_command], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        start_new_session=True)
    try:
        output, _ = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired as error:
        kill_process_tree(process)
        process.communicate()
        raise ValueError('Environment script timed out') from error
    require(process.returncode == 0, 'Environment script failed with exit code ' + str(process.returncode))
    require(output and output.endswith(b'\0'), 'Environment script did not produce a complete environment')
    result = {}
    for entry in output[:-1].split(b'\0'):
        key, separator, value = entry.partition(b'=')
        require(separator and key, 'Malformed environment record')
        result[os.fsdecode(key)] = os.fsdecode(value)
    require(digest(path) == before, 'Environment script changed while being loaded')
    return result, {str(path): before}


def run_process(command, cwd, env, timeout, log):
    require(timeout > 0, 'Timeout must be positive')
    start = time.monotonic()
    with Path(log).open('wb') as output:
        process = subprocess.Popen(command, cwd=cwd, env=env, stdout=output, stderr=subprocess.STDOUT,
                                   start_new_session=(os.name != 'nt'))
        timed_out = False
        try:
            code = process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            kill_process_tree(process)
            code = process.wait()
    return {'command': list(map(str, command)), 'returncode': code, 'timed_out': timed_out,
            'seconds': round(time.monotonic() - start, 3)}


class Runtime:
    def __init__(self, args, job):
        self.args, self.job, self.runs, self.sources = args, Path(job), [], {}
        self.root = Path(args.cadence_root).resolve(strict=True)
        self.bin = self.root / ('tools/bin' if os.name == 'nt' else 'tools.lnx86/bin')
        self.env, environment_sources = load_environment(getattr(args, 'env_file', None), min(args.timeout, 15))
        self.sources.update(environment_sources)
        self.environment = {'mode': 'sourced' if environment_sources else 'inherited',
                            'script_sources': environment_sources}
        local_env = self.job / 'pcbenv'
        local_env.mkdir()
        (local_env / 'env').write_text('source $ALLEGRO_INSTALL_DIR/text/env\n', encoding='utf-8')
        self.env.update(CDSROOT=str(self.root), CDS_AUTO_64BIT='ALL',
                        ALLEGRO_PCBENV=str(local_env),
                        ALLEGRO_MWUSER_DIR=str(self.job / 'mw'),
                        PATH=str(self.bin) + os.pathsep + self.env.get('PATH', ''))
        if args.license:
            self.env['CDS_LIC_FILE'] = args.license
        self.environment['license_configured'] = bool(self.env.get('CDS_LIC_FILE') or self.env.get('LM_LICENSE_FILE'))
        if os.name != 'nt':
            self.env.pop('DISPLAY', None)
            self.env.pop('WAYLAND_DISPLAY', None)
        # Do not record environment variables or license contents in reports.

    def call(self, program, arguments, output=None):
        binary = self.bin / (program + '.exe' if os.name == 'nt' else program)
        require(binary.is_file(), 'Native program missing: ' + str(binary))
        command = [str(binary), *map(str, arguments)]
        if os.name != 'nt':
            xvfb = shutil.which('xvfb-run', path=self.env.get('PATH'))
            require(xvfb, 'Linux native execution requires xvfb-run')
            command = [xvfb, '-a', *command]
        log = self.job / (str(len(self.runs) + 1).zfill(2) + '-' + program + '.log')
        result = run_process(command, self.job, self.env, self.args.timeout, log)
        result['executable_sha256'] = digest(binary)
        self.runs.append(result)
        require(result['returncode'] == 0 and not result['timed_out'], 'Native command failed or timed out: ' + program)
        # Some Cadence batch tools return zero after a failed operation.
        if log.is_file():
            errors = [line.strip() for line in log.read_text(encoding='utf-8', errors='replace').splitlines()
                      if re.match(r'^\s*\**\s*ERROR(?:\s*\([^)]*\))?\s*:', line, re.I)]
            require(not errors, 'Native log reports an error: ' + ('; '.join(errors[:3]))[:1000])
        if output:
            target = self.job / output
            require(target.is_file() and target.stat().st_size > 0, 'Native output missing: ' + output)

    def finish(self):
        require(all(Path(p).is_file() and digest(p) == sha for p, sha in self.sources.items()), 'An input changed during execution')
        return {'sources_unchanged': True, 'sources': self.sources, 'runs': self.runs,
                'environment': self.environment}


def stage_libraries(runtime, paths):
    require(paths, 'Explicit library directories/files are required for PST import')
    found = {}
    for path in map(Path, paths):
        require(path.exists(), 'Library path missing: ' + str(path))
        files = sorted(path.iterdir()) if path.is_dir() else [path]
        for source in files:
            if not source.is_file() or source.suffix.lower() not in ('.psm', '.pad', '.ssm', '.fsm'):
                continue
            name = source.name.lower()
            if name in found:
                require(digest(source) == found[name], 'Conflicting library files: ' + name)
            else:
                stage(source, runtime.job / 'library' / name, runtime.sources)
                found[name] = digest(source)
    require(found, 'No compiled library files found')
    (runtime.job / 'pcbenv' / 'env').write_text(
        'source $ALLEGRO_INSTALL_DIR/text/env\nset psmpath = ./library\nset padpath = ./library\n', encoding='utf-8')
    return found


def import_board(runtime, directory, seed, libraries, encoding):
    snapshot = read_netlist(directory, encoding)
    for name in (*snapshot['sources'], *snapshot['companions']):
        stage(Path(directory) / name, runtime.job / 'netlist' / name, runtime.sources)
        require(digest(runtime.job / 'netlist' / name) == {**snapshot['sources'], **snapshot['companions']}[name],
                'Netlist changed after parsing: ' + name)
    found = stage_libraries(runtime, libraries)
    for component in snapshot['components'].values():
        require(component['symbol'].lower() + '.psm' in found, 'Missing compiled footprint: ' + component['symbol'])
    arguments = ['-e', '-i', 'netlist']
    if seed:
        stage(seed, runtime.job / 'seed.brd', runtime.sources)
        arguments += ['seed.brd', 'imported.brd']
    else:
        arguments += ['-n', 'new.brd', 'imported.brd']
    runtime.call('netrev', arguments, 'imported.brd')
    runtime.call('report', ['-v', 'cpn', 'imported.brd', 'connectivity.txt'], 'connectivity.txt')
    matched = verify_connectivity(snapshot, runtime.job / 'connectivity.txt')
    return {'status': 'native_import_candidate', 'native_verified': False, **matched,
            'pending': ['footprint geometry and properties readback'],
            'netlist': snapshot}


def place_board(runtime, board, plan, netlist, libraries=()):
    stage(board, runtime.job / 'source.brd', runtime.sources)
    if libraries:
        stage_libraries(runtime, libraries)
    runtime.call('plctxt', ['-r', '-m', 'source.brd', 'placed.brd', 'place_txt.txt'], 'placed.brd')
    # No -z (ignore FIXED), -s (save despite errors), -c or -p origin changes.
    runtime.call('plctxt', ['placed.brd', 'readback.brd', 'actual.txt'], 'actual.txt')
    actual = read_placement(runtime.job / 'actual.txt')
    matched = verify_placement(plan, actual)
    runtime.call('report', ['-v', 'cpn', 'placed.brd', 'connectivity.txt'], 'connectivity.txt')
    matched.update(verify_connectivity(netlist, runtime.job / 'connectivity.txt'))
    return {'status': 'native_placement_matched', **matched, 'native_verified': False,
            'pending': ['physical pin positions and routed continuity', 'FIXED properties requested by the model',
                        'native outline/keepouts/DRC and engineering acceptance']}


REPORTS = ('drc', 'drc_shorts', 'net', 'npr', 'sum', 'ucn', 'upc', 'pcp', 'cpn', 'spn', 'pad', 'elw', 'vialist_net', 'x-section', 'waived_drc')


def report_board(runtime, board, codes):
    stage(board, runtime.job / 'source.brd', runtime.sources)
    for code in codes:
        require(code in REPORTS, 'Unsupported report code')
        runtime.call('report', ['-v', code, 'source.brd', code + '.txt'], code + '.txt')
    return {'status': 'native_reports_generated', 'native_verified': False,
            'pending': ['AI review of native reports against the requirements']}
