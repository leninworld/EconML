"""Baseline-only steps; standard-library control code, no product mutation."""
import hashlib
import importlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

P = Path('/packet')
W = Path('/work')
E = W / 'evidence'
E.mkdir(exist_ok=True)
PY = str(W / 'app/bin/python')
EXTENSIONS = ('econml.policy._forest._criterion', 'econml.grf._criterion', 'econml.grf._utils',
              'econml.tree._tree', 'econml.tree._splitter', 'econml.tree._criterion', 'econml.tree._utils')


def save(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n')


def metrics():
    root = Path('/sys/fs/cgroup')
    result = {name: (root / name).read_text() for name in
              ('memory.current', 'memory.peak', 'memory.events', 'memory.max',
               'pids.current', 'pids.peak', 'pids.events', 'pids.max', 'cpu.stat')}
    result['shm'] = shutil.disk_usage('/dev/shm')._asdict()
    result['uname'] = list(os.uname())
    result['affinity'] = sorted(os.sched_getaffinity(0))
    return result


def call(args, cwd=None, env=None, accepted=(0,)):
    print('STEP_COMMAND', json.dumps(args), flush=True)
    outcome = subprocess.run(args, cwd=cwd, env=env)
    assert outcome.returncode in accepted, ('STEP_EXIT', outcome.returncode, args)
    return outcome.returncode


def verify_source():
    manifest = json.loads((P / 'source-manifest.json').read_text())
    for row in manifest:
        data = (W / 'src' / row['path']).read_bytes()
        assert hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest() == row['oid'], row['path']


def verify_closure():
    expected = json.loads((P / 'runtime-expected.json').read_text())
    code = ('import importlib.metadata,json,re; print(json.dumps({re.sub(r"[-_.]+","-",d.metadata["Name"]).lower():d.version '
            'for d in importlib.metadata.distributions()}))')
    actual = json.loads(subprocess.check_output([PY, '-I', '-c', code]))
    normalized = {re.sub(r'[-_.]+', '-', name).lower(): version for name, version in expected.items()}
    assert actual.pop('econml', None) is not None
    assert actual == normalized, {'missing_or_changed': {k: v for k, v in normalized.items() if actual.get(k) != v},
                                  'extra': sorted(actual.keys() - normalized.keys())}
    save(E / 'installed-runtime.json', actual)
    call(['uv', 'pip', 'check', '--python', PY])
    with (E / 'installed-freeze.txt').open('w') as stream:
        subprocess.run(['uv', 'pip', 'freeze', '--python', PY], stdout=stream, check=True)


def install():
    source = Path('/source')
    manifest = json.loads((P / 'source-manifest.json').read_text())
    assert len(manifest) == 299 and not (W / 'src').exists()
    (W / 'src').mkdir()
    for row in manifest:
        path = Path(row['path'])
        assert not path.is_absolute() and '..' not in path.parts
        src = source / path
        assert src.is_file() and not src.is_symlink()
        data = src.read_bytes()
        oid = hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()
        assert oid == row['oid'], row['path']
        dest = W / 'src' / path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        dest.chmod(0o755 if row['mode'] == '100755' else 0o644)
    save(E / 'source-verified.json', {'pin': json.loads((P / 'plan.json').read_text())['source'],
                                     'files': len(manifest), 'bytes': sum((source / x['path']).stat().st_size for x in manifest)})
    for name in ('app', 'buildenv'):
        call(['python', '-m', 'venv', '--without-pip', str(W / name)])
    call(['uv', 'pip', 'install', '--python', PY, '--require-hashes', '--only-binary', ':all:',
          '--no-deps', '-r', '/packet/runtime.txt'])
    call(['uv', 'pip', 'install', '--python', '/work/buildenv/bin/python', '--require-hashes',
          '--only-binary', ':all:', '--no-deps', '-r', '/packet/build-requirements.txt'])
    with (E / 'buildenv-freeze.txt').open('w') as stream:
        subprocess.run(['uv', 'pip', 'freeze', '--python', '/work/buildenv/bin/python'], stdout=stream, check=True)
    shutil.copyfile('/bootstrap/debian-versions.txt', E / 'debian-versions.txt')
    shutil.copyfile('/bootstrap/uv-version.txt', E / 'uv-version.txt')


def build_probe():
    call(['uv', 'pip', 'install', '--offline', '--python', PY, '--no-deps',
          '--build-constraint', '/packet/build-constraints.txt', '-e', '/work/src'])
    verify_source()
    verify_closure()
    assert platform.python_version() == '3.13.16' and platform.machine() == 'x86_64'
    assert len(os.sched_getaffinity(0)) == 4
    assert shutil.disk_usage('/dev/shm').total >= 4 * 1024**3
    metrics()  # Require kernel metrics before an expensive product step.
    call([PY, '/packet/inside.py', 'imports'], cwd='/work/src')
    env = dict(os.environ, PYTHONPATH='/packet')
    call([PY, '-m', 'pytest', '-n', 'auto', '-o', 'addopts=', '-p', 'worker_probe',
          '--confcutdir=/packet', '/packet/probe_test.py', '-q'], cwd='/work', env=env)
    assert json.loads((E / 'xdist-workers.json').read_text())['workers'] == 4
    verify_source()


def imports():
    import numpy as np
    import scipy
    import sklearn
    import lightgbm
    import numba
    import ray
    for name in EXTENSIONS:
        mod = importlib.import_module(name)
        assert mod.__file__.endswith('.so') and str(W / 'src') in mod.__file__
    @numba.njit
    def plus_one(x):
        return x + 1
    assert plus_one(2) == 3
    assert np.isfinite(lightgbm.LGBMRegressor(n_estimators=2, verbosity=-1).fit(
        np.arange(40).reshape(20, 2), np.arange(20)).predict([[1, 2]])).all()
    ray.init(num_cpus=1, include_dashboard=False)
    try:
        assert ray.is_initialized()
    finally:
        ray.shutdown()
    save(E / 'P0-imports.json', {'python': sys.version, 'numpy': np.__version__, 'scipy': scipy.__version__,
                                'sklearn': sklearn.__version__, 'lightgbm': lightgbm.__version__,
                                'numba': numba.__version__, 'ray': ray.__version__, 'offline_ray': True})


def ray_group():
    env = dict(os.environ, PYTEST_ADDOPTS='-m "ray"')
    code = call([PY, '-m', 'pytest'], cwd='/work/src', env=env, accepted=(0, 1))
    verify_source()
    junit = W / 'src/junit/test-results.xml'
    root = ET.parse(junit).getroot()
    cases = root.findall('.//testcase')
    assert cases and not root.findall('.//error'), 'Incomplete/errored collection is HOLD'
    shutil.copyfile(junit, E / 'ray-junit.xml')
    save(E / 'ray-summary.json', {'pytest_exit': code, 'cases': len(cases),
                                 'failures': len(root.findall('.//failure')),
                                 'skips': len(root.findall('.//skipped')),
                                 'assessment': 'MEASUREMENT_COMPLETE_REVIEW_REQUIRED',
                                 'baseline_failure_classification': 'PENDING_ACTUAL_REVIEW'})


def wheel():
    call(['uv', 'build', '--wheel', '--offline', '--build-constraint', '/packet/build-constraints.txt',
          '--out-dir', '/work/dist', '/work/src'])
    call(['python', '-m', 'venv', '--without-pip', '/work/wheel-env'])
    call(['uv', 'pip', 'install', '--offline', '--python', '/work/wheel-env/bin/python', '--require-hashes',
          '--only-binary', ':all:', '--no-deps', '-r', '/packet/runtime.txt'])
    files = list((W / 'dist').glob('*.whl'))
    assert len(files) == 1
    call(['uv', 'pip', 'install', '--offline', '--python', '/work/wheel-env/bin/python', '--no-deps', str(files[0])])
    call(['/work/wheel-env/bin/python', '-I', '/packet/inside.py', 'wheel_smoke'], cwd='/work')
    save(E / 'wheel-digest.json', {'file': files[0].name, 'sha256': hashlib.sha256(files[0].read_bytes()).hexdigest(),
                                  'manylinux': False})


def wheel_smoke():
    import numpy as np
    import econml
    from econml.dml import LinearDML
    from sklearn.linear_model import LinearRegression
    paths = [econml.__file__] + [importlib.import_module(n).__file__ for n in EXTENSIONS]
    assert all('/work/wheel-env/lib/python3.13/site-packages/' in p for p in paths)
    assert all(p.endswith('.so') for p in paths[1:])
    rng = np.random.default_rng(8)
    X = rng.normal(size=(100, 2))
    T = rng.normal(size=100)
    Y = 2 * T + X[:, 0] + rng.normal(size=100)
    est = LinearDML(model_y=LinearRegression(), model_t=LinearRegression(), random_state=17)
    est.fit(Y, T, X=X)
    assert np.isfinite(est.effect(X[:5])).all()
    save(E / 'wheel-smoke.json', {'paths': paths, 'fitted_smoke': True})


def fixture(kind):
    if kind == 'success':
        time.sleep(20)
        print('F0_20_SECOND_SUCCESS', flush=True)
    elif kind == 'fail':
        print('F0_EXPECTED_EXIT_3', flush=True)
        sys.exit(3)
    elif kind == 'oom':
        block = bytearray(512 * 1024**2)
        time.sleep(20)
        assert block
    elif kind in ('timeout', 'deadline'):
        time.sleep(20)
    else:
        raise ValueError(kind)


if __name__ == '__main__':
    mode = sys.argv[1]
    if mode == 'metrics':
        print(json.dumps(metrics()))
    elif mode == 'fixture':
        fixture(sys.argv[2])
    else:
        actions = {'install': install, 'build': build_probe, 'ray': ray_group,
                   'wheel': wheel, 'imports': imports, 'wheel_smoke': wheel_smoke}
        started = time.time()
        receipt = {'phase': mode, 'started': started, 'success': False}
        try:
            actions[mode]()
            receipt['success'] = True
        except BaseException as exc:
            receipt['first_failure'] = {'type': type(exc).__name__, 'message': str(exc)}
            raise
        finally:
            receipt['elapsed'] = time.time() - started
            try:
                receipt['metrics'] = metrics()
            except Exception as exc:
                receipt['metrics_error'] = type(exc).__name__ + ': ' + str(exc)
            save(E / (mode + '-receipt.json'), receipt)
