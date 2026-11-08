"""Fetch exactly one hash-pinned uv wheel during the hosted image build."""
import hashlib
import json
from pathlib import Path
import subprocess
import urllib.request

spec = json.loads(Path('/bootstrap/uv-wheel.json').read_text())
assert spec['url'].startswith('https://files.pythonhosted.org/')
request = urllib.request.Request(spec['url'], headers={'User-Agent': 'econml686-baseline-validation'})
with urllib.request.urlopen(request, timeout=90) as response:
    assert response.status == 200
    data = response.read(spec['size'] + 1)
assert len(data) == spec['size']
assert hashlib.sha256(data).hexdigest() == spec['digests']['sha256']
wheel = Path('/bootstrap') / spec['filename']
wheel.write_bytes(data)
subprocess.run(['python', '-m', 'pip', 'install', '--no-index', '--no-deps',
                '--disable-pip-version-check', '--no-cache-dir', str(wheel)], check=True)
subprocess.run(['uv', '--version'], check=True)
