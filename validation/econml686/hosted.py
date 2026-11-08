"""One hosted M0 attempt. Reuse proven bounded commands; no periodic observer."""
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import sys
import time

from bounded import LimitAbort, command, limit, save

P = Path(__file__).resolve().parent
PLAN = json.loads((P / 'plan.json').read_text())
assert os.environ.get('GITHUB_ACTIONS') == 'true'
assert os.environ.get('RUNNER_ENVIRONMENT') == 'github-hosted'
assert os.environ.get('GITHUB_REPOSITORY') == 'leninworld/EconML'
assert os.environ.get('GITHUB_REF') == 'refs/heads/' + PLAN['branch']
assert os.environ.get('GITHUB_RUN_ATTEMPT') == '1'
assert os.environ.get('GITHUB_RUN_NUMBER') == '1', 'ONE_SHOT_WORKFLOW_RUN_NUMBER'
assert os.environ.get('GITHUB_EVENT_NAME') == 'push', 'PUSH_EVENT_ONLY'
assert platform.system() == 'Linux' and platform.machine() == 'x86_64'
RUN = os.environ['GITHUB_RUN_ID']
assert RUN.isdigit() and PLAN['execution_enabled']
START = float(os.environ['M0_STARTED'])
END = START + PLAN['absolute_seconds']
ROOT = Path(os.environ['RUNNER_TEMP']) / ('econml686-m0-' + RUN)
DEADLINE_FIXTURE = sys.argv[1:] == ['deadline-fixture']
assert not sys.argv[1:] or DEADLINE_FIXTURE
if DEADLINE_FIXTURE:
    assert ROOT.is_dir()
else:
    ROOT.mkdir(exist_ok=False)
E = ROOT / 'evidence' / 'deadline-child' if DEADLINE_FIXTURE else ROOT / 'evidence'
E.mkdir(exist_ok=False)
FIXTURE_END = time.time() + 5 if DEADLINE_FIXTURE else None
SOURCE = Path(os.environ['GITHUB_WORKSPACE']) / 'upstream'
IMAGE = 'econml686-m0:' + RUN
VOLUME = 'econml686-m0-' + RUN
DOCKER_ROOT = None
routes = [line.split()[0] for line in Path('/proc/net/route').read_text().splitlines()[1:]
          if line.split()[1] == '00000000']
assert len(set(routes)) == 1
RX = Path('/sys/class/net') / routes[0] / 'statistics/rx_bytes'
RX_START = int(RX.read_text())
OWNED = []


def guard():
    limit(time.time() < END, 'ONE_M0_DEADLINE')
    if FIXTURE_END is not None:
        limit(time.time() < FIXTURE_END, 'F0_COMPRESSED_GLOBAL_DEADLINE')
    available = int(re.search(r'^MemAvailable:\s+(\d+)', Path('/proc/meminfo').read_text(), re.M)[1]) * 1024
    limit(available > 1024**3, 'HOST_MEMORY_PRESSURE')
    for path in (ROOT, DOCKER_ROOT):
        if path:
            limit(shutil.disk_usage(path).free > 6 * 1024**3, 'HOST_DISK_PRESSURE')
    limit(int(RX.read_text()) - RX_START < PLAN['network_bytes_cap'], 'NETWORK_CAP')
    limit(sum(p.stat().st_size for p in E.rglob('*') if p.is_file()) < PLAN['artifact_cap'], 'EVIDENCE_CAP')
    image_cache = ROOT / 'image-cache'
    if image_cache.exists():
        limit(sum(p.stat().st_size for p in image_cache.iterdir() if p.is_file()) < 5 * 1024**3, 'IMAGE_CACHE_CAP')


def run(label, args, seconds=30, cap=2*1024**2, guarded=True):
    seconds = min(seconds, max(1, END-time.time())) if guarded else seconds
    return command(args, seconds, cap, guard if guarded else lambda: None, log=E / (label + '.log'))


def stop_owned(name, receipt):
    """Stop only this run's labelled container, even after the global guard denies."""
    try:
        identity = json.loads(run(name + '-identity-before-stop',
            ['docker', 'inspect', '--format', '{{json .}}', name], guarded=False))
        assert identity['Config']['Labels'].get('econml686.run') == RUN
        assert identity['Name'] == '/' + name
        receipt['stop_requested_at'] = time.time()
        try:
            receipt['stop_output'] = run(name + '-stop', ['docker', 'stop', '-t', '10', name],
                                         seconds=25, guarded=False).decode()
        except Exception as exc:
            receipt['stop_error'] = type(exc).__name__ + ': ' + str(exc)
        state = json.loads(run(name + '-state-after-stop',
            ['docker', 'inspect', '--format', '{{json .State}}', name], guarded=False))
        receipt['final_state'] = state
        receipt['confirmed_stopped'] = not state['Running'] and not state['Restarting']
    except Exception as exc:
        receipt['stop_inspection_error'] = type(exc).__name__ + ': ' + str(exc)
        receipt['confirmed_stopped'] = False


def phase(label, args, seconds, memory='6g', pids=2048, bridge=False, fixture=False):
    guard()
    name = 'econml686-m0-' + RUN + '-' + label
    assert name not in OWNED and not (E / (label + '-phase.json')).exists()
    receipt = {'phase': label, 'started': time.time(), 'ok': False, 'command': args,
               'memory': memory, 'pids': pids, 'network': 'bridge' if bridge else 'none'}
    OWNED.append(name)  # Capture possible creation even if the CLI fails after creating it.
    first = None
    try:
        create = ['docker', 'create', '--name', name, '--label', 'econml686.run=' + RUN,
            '--label', 'purpose=econml686-m0', '--cpuset-cpus', '0-3', '--cpus', '4',
            '--memory', memory, '--memory-swap', memory, '--pids-limit', str(pids),
            '--shm-size', '4g', '--read-only', '--user', '1000:1000', '--cap-drop', 'ALL',
            '--security-opt', 'no-new-privileges', '--log-driver', 'none',
            '--network', 'bridge' if bridge else 'none', '--workdir', '/work',
            '--mount', 'type=volume,src=' + VOLUME + ',dst=/work',
            '--mount', 'type=bind,src=' + str(P) + ',dst=/packet,readonly',
            '--tmpfs', '/tmp:rw,exec,nosuid,nodev,uid=1000,gid=1000,size=1g']
        if not fixture:
            create += ['--mount', 'type=bind,src=' + str(SOURCE) + ',dst=/source,readonly']
        settings = {'HOME': '/work/home', 'UV_CACHE_DIR': '/work/uv-cache', 'UV_HTTP_RETRIES': '0',
                    'UV_HTTP_TIMEOUT': '60', 'UV_PYTHON_DOWNLOADS': 'never', 'UV_NO_CONFIG': '1',
                    'NUMBA_CACHE_DIR': '/work/numba-cache', 'MPLCONFIGDIR': '/work/mpl-cache',
                    'MPLBACKEND': 'Agg', 'RAY_USAGE_STATS_ENABLED': '0', 'RAY_TMPDIR': '/work/raytmp',
                    'COVERAGE_PROCESS_START': 'pyproject.toml'}
        for key, value in settings.items():
            create += ['--env', key + '=' + value]
        create += [IMAGE]
        cid = run(label + '-create', create).decode().strip()
        assert re.fullmatch('[a-f0-9]{64}', cid)
        receipt['container_id'] = cid
        run(label + '-start', ['docker', 'start', name])
        cap = min(seconds, max(1, END - time.time() - 45))
        run(label + '-step', ['docker', 'exec', name, 'timeout', '-k', '30', str(cap)] + args,
            seconds=cap + 35, cap=8*1024**2)
        receipt['ok'] = True
    except BaseException as exc:
        first = exc
        receipt['first_failure'] = {'type': type(exc).__name__, 'message': str(exc), 'at': time.time()}
        save(E / (label + '-first-failure.json'), receipt['first_failure'])
    finally:
        # This is a single end-of-phase read, never a sampling loop.
        try:
            data = run(label + '-kernel-metrics',
                ['docker', 'exec', name, 'python', '/packet/inside.py', 'metrics'], guarded=False)
            receipt['metrics'] = json.loads(data)
        except Exception as exc:
            receipt['metrics_error'] = type(exc).__name__ + ': ' + str(exc)
        stop_owned(name, receipt)
        receipt['elapsed'] = time.time() - receipt['started']
        receipt['ok'] = receipt['ok'] and receipt.get('confirmed_stopped', False) and 'metrics' in receipt
        save(E / (label + '-phase.json'), receipt)
    if isinstance(first, LimitAbort):
        raise first
    return receipt


def events(row, name):
    return {k: int(v) for k, v in (line.split() for line in row['metrics'][name].splitlines())}


class PhaseFailure(Exception):
    """A retained ordinary phase failure that blocks dependent steps."""


def require_phase(*args, **kwargs):
    row = phase(*args, **kwargs)
    if not row['ok']:
        raise PhaseFailure(row['phase'])
    return row


def fixture_cases():
    base = ['python', '/packet/inside.py', 'fixture']
    success = phase('f0-success', base + ['success'], 35, memory='512m', pids=128, fixture=True)
    assert success['ok'] and success['elapsed'] >= 20
    assert b'F0_20_SECOND_SUCCESS' in (E / 'f0-success-step.log').read_bytes()
    try:
        require_phase('f0-fail', base + ['fail'], 15, memory='512m', pids=128, fixture=True)
        require_phase('f0-dependent', base + ['success'], 35, memory='512m', pids=128, fixture=True)
        raise AssertionError('Expected PhaseFailure did not occur')
    except PhaseFailure as exc:
        assert str(exc) == 'f0-fail'
    bad = json.loads((E / 'f0-fail-phase.json').read_text())
    assert not bad['ok'] and bad['confirmed_stopped']
    assert 'command exit 3,' in bad['first_failure']['message']
    assert b'F0_EXPECTED_EXIT_3' in (E / 'f0-fail-step.log').read_bytes()
    assert not (E / 'f0-dependent-phase.json').exists()
    assert not any(name.endswith('-f0-dependent') for name in OWNED)
    oom = phase('f0-oom', base + ['oom'], 25, memory='256m', pids=128, fixture=True)
    assert not oom['ok'] and oom['confirmed_stopped'] and events(oom, 'memory.events')['oom_kill'] >= 1
    row = phase('f0-timeout', base + ['timeout'], 3, memory='512m', pids=128, fixture=True)
    assert not row['ok'] and row['confirmed_stopped'] and 'command exit 124,' in row['first_failure']['message']
    # The same controller/guard/phase path in a fixture subprocess, under the unchanged outer deadline.
    # Its shorter surrogate deadline is deliberately expired; no actual M0 clock is reset.
    command([sys.executable, str(P / 'hosted.py'), 'deadline-fixture'],
            min(60, END-time.time()), 1024**2, guard, expected=77, log=E / 'f0-global-deadline.log')
    deadline = json.loads((E / 'deadline-child/f0-global-deadline-phase.json').read_text())
    assert not deadline['ok'] and deadline['confirmed_stopped']
    assert deadline['first_failure']['message'] == 'F0_COMPRESSED_GLOBAL_DEADLINE'
    save(E / 'F0.json', {'status': 'PASS', 'real_cases': ['20s', 'exit3-blocks-next', 'oom', 'timeout', 'compressed-global-deadline'],
                         'global_deadline': 'Outer LimitAbort propagates. Only the nested fixture sentinel is expected; outer clock unchanged.'})


if DEADLINE_FIXTURE:
    try:
        phase('f0-global-deadline', ['python', '/packet/inside.py', 'fixture', 'deadline'],
              30, memory='512m', pids=128, fixture=True)
        raise AssertionError('Compressed guard did not expire')
    except LimitAbort as exc:
        if str(exc) != 'F0_COMPRESSED_GLOBAL_DEADLINE':
            raise
        sys.exit(77)


summary = {'status': 'ADMISSION_NOT_MET_NO_PROJECT_CODE_RUN', 'source': PLAN['source'],
           'started': START, 'full_product_validation': False}
admitted = False
try:
    initial_available = int(re.search(r'^MemAvailable:\s+(\d+)', Path('/proc/meminfo').read_text(), re.M)[1]) * 1024
    save(E / 'pre-admission-observations.json', {'mem_available': initial_available,
         'affinity': sorted(os.sched_getaffinity(0)), 'runner_disk_free': shutil.disk_usage(ROOT).free,
         'docker_information': 'NOT_YET_READ'})
    guard()
    for name, digest in json.loads((P / 'file-hashes.json').read_text()).items():
        assert hashlib.sha256((P / name).read_bytes()).hexdigest() == digest, name
    info = json.loads(run('docker-info', ['docker', 'info', '--format', '{{json .}}']))
    DOCKER_ROOT = info['DockerRootDir']
    available = int(re.search(r'^MemAvailable:\s+(\d+)', Path('/proc/meminfo').read_text(), re.M)[1]) * 1024
    admission = {'mem_available': available, 'mem_total': info['MemTotal'], 'docker_info': info,
                 'docker_root': DOCKER_ROOT, 'disk_free': None, 'cpus': info['NCPU'],
                 'cgroup_version': info['CgroupVersion'], 'affinity': sorted(os.sched_getaffinity(0)),
                 'no_mac_access': True}
    save(E / 'host-admission.json', admission)
    admission['disk_free'] = shutil.disk_usage(DOCKER_ROOT).free
    save(E / 'host-admission.json', admission)
    assert info['OSType'] == 'linux', 'HOST_OS_LINUX_REQUIRED'
    assert info['Architecture'] in ('x86_64', 'amd64'), 'HOST_NATIVE_AMD64_REQUIRED'
    assert info['CgroupVersion'] == '2', 'CGROUP_V2_REQUIRED'
    assert info['NCPU'] >= 4, 'HOST_AT_LEAST_4_CPUS_REQUIRED'
    assert info['MemTotal'] >= 15 * 1024**3, 'HOST_15_GIB_TOTAL_REQUIRED'
    assert {0, 1, 2, 3}.issubset(os.sched_getaffinity(0)), 'HOST_CPUSET_0_TO_3_REQUIRED'
    assert available >= 14 * 1024**3, 'HOST_14_GIB_AVAILABLE_REQUIRED'
    assert admission['disk_free'] >= 20 * 1024**3, 'HOST_20_GIB_DISK_FREE_REQUIRED'
    assert run('source-head', ['git', '-C', str(SOURCE), 'rev-parse', 'HEAD']).decode().strip() == PLAN['source'], 'SOURCE_PIN_MISMATCH'
    assert run('source-clean', ['git', '-C', str(SOURCE), 'status', '--porcelain']) == b'', 'SOURCE_NOT_CLEAN'
    admitted = True
    summary['status'] = 'FAILED'
    run('image-build', ['docker', 'build', '--network', 'default', '--label', 'econml686.run=' + RUN,
                        '--tag', IMAGE, str(P)], 600, cap=8*1024**2)
    image = json.loads(run('image-inspect', ['docker', 'image', 'inspect', IMAGE]))[0]
    assert image['Architecture'] == 'amd64' and image['Os'] == 'linux'
    summary['image_id'] = image['Id']
    # Hosted runners are ephemeral: retain the exact image bytes for a later identical baseline/candidate lane.
    cache = ROOT / 'image-cache'
    cache.mkdir()
    archive = cache / 'econml686-m0-image.tar'
    run('image-save', ['docker', 'image', 'save', '--output', str(archive), IMAGE], 180, cap=4096)
    assert archive.stat().st_size <= 3 * 1024**3
    run('image-compress', ['gzip', '-1', '--keep', str(archive)], 180, cap=4096)
    compressed = Path(str(archive) + '.gz')
    assert compressed.stat().st_size <= 2 * 1024**3
    with compressed.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    run('image-gzip-check', ['gzip', '--test', str(compressed)], 180, cap=4096)
    save(E / 'image-cache-identity.json', {'image_id': image['Id'], 'tag': IMAGE, 'archive': compressed.name,
                                         'compressed_bytes': compressed.stat().st_size, 'sha256': digest})
    run('volume-create', ['docker', 'volume', 'create', '--label', 'econml686.run=' + RUN, VOLUME])
    fixture_cases()
    rows = []
    for name, seconds, memory, pids in [('install', 600, '4g', 2048), ('build', 600, '6g', 2048),
                                        ('ray', 1500, '12g', 8192), ('wheel', 480, '6g', 2048)]:
        if name == 'wheel' and END - time.time() < 720:
            summary['wheel'] = 'DEFERRED_TO_FULL_PACKET_LESS_THAN_12_MINUTES_REMAIN'
            break
        row = require_phase(name, ['python', '/packet/inside.py', name], seconds, memory, pids, bridge=name == 'install')
        rows.append(row)
        assert row['ok'], name + ': first failure retained, dependent phases stopped'
        assert events(row, 'memory.events')['oom_kill'] == 0, name + ': OOM HOLD'
        assert events(row, 'pids.events')['max'] == 0, name + ': PID limit HOLD'
    summary['status'] = 'MEASUREMENT_FINISHED_REVIEW_REQUIRED'
    summary['phases'] = rows
except BaseException as exc:
    if not admitted:
        summary['status'] = 'ADMISSION_NOT_MET_NO_PROJECT_CODE_RUN'
    summary['first_failure'] = {'type': type(exc).__name__, 'message': str(exc), 'at': time.time()}
    save(E / 'first-failure.json', summary['first_failure'])
    raise
finally:
    # Copy only synthetic baseline evidence, never a whole venv, cache or source tree.
    # Stopped containers and the labelled volume are retained; no rm/prune/reset.
    if OWNED:
        try:
            run('copy-owned-evidence', ['docker', 'cp', OWNED[-1] + ':/work/evidence', str(E / 'inside')],
                seconds=30, cap=4096, guarded=False)
        except Exception as exc:
            summary['evidence_copy_error'] = type(exc).__name__ + ': ' + str(exc)
    summary.update(elapsed=time.time()-START, received_bytes=int(RX.read_text())-RX_START,
                   retained_containers=OWNED, retained_volume=VOLUME, image=IMAGE)
    save(E / 'summary.json', summary)
