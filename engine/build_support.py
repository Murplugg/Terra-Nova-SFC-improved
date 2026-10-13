"""Input integrity, layout validation and declared-file access checks."""
import hashlib
import json
import os
import sys
from pathlib import Path

DOS_SHA = '2d67f93683d5e7da0ca73004aeb89a7647061c664308ad7019134477b133a59a'
ORIGINAL_SHA = 'b762c54509f1716282c4d357a72013b8d84ba25f17b0483b733678ff81e63dd1'
KIT = Path(__file__).resolve().parent


def digest(data):
    return hashlib.sha256(data).hexdigest()


def verify_sources():
    manifest = json.loads((KIT / 'source-manifest.json').read_text(encoding='utf-8'))
    for name, expected in manifest['files'].items():
        path = (KIT / name).resolve()
        if not path.is_relative_to(KIT) or digest(path.read_bytes()) != expected:
            raise ValueError('Source integrity check failed: ' + name)
    return manifest


def validate_layout(config):
    required = {'game_root', 'cd_root', 'audio_dll', 'log_root', 'config_file', 'run_ms'}
    if set(config) != required or config['run_ms'] != 0:
        raise ValueError('Expected the six foundation layout fields and run_ms=0')
    for name in required - {'run_ms'}:
        value = config[name]
        if not isinstance(value, str) or not Path(value).is_absolute() or '\0' in value:
            raise ValueError('Invalid absolute runtime path: ' + name)
        if len(value.encode('ascii')) > 240:
            raise ValueError('Runtime path too long: ' + name)
    return config


def install_audit(allowed):
    """Reject unexpected Python file access; log permitted paths for review.

    This is a reproducibility check, not a security sandbox for native libraries.
    """
    accesses = set()
    allowed = [p.resolve() for p in allowed]

    def audit(event, args):
        if event != 'open' or isinstance(args[0], int):
            return
        path = Path(os.fsdecode(args[0])).resolve()
        if not any(path == root or path.is_relative_to(root) for root in allowed):
            raise RuntimeError('Undeclared file access: ' + str(path))
        accesses.add(str(path))

    sys.addaudithook(audit)
    return accesses
