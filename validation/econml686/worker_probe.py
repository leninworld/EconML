"""Record actual xdist node count in the synthetic dependency probe only."""
import json
from pathlib import Path


def pytest_xdist_setupnodes(config, specs):
    Path('/work/evidence/xdist-workers.json').write_text(json.dumps({'workers': len(specs)}))
