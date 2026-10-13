"""Run synthetic tests, optionally adding routines extracted from retail."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'engine'))
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--retail-exe', type=Path, help='Original English retail __FF.EXE for retained-code tests')
args = parser.parse_args()
if args.retail_exe:
    data = args.retail_exe.read_bytes()
    if hashlib.sha256(data).hexdigest() != 'b762c54509f1716282c4d357a72013b8d84ba25f17b0483b733678ff81e63dd1':
        parser.error('Unsupported retail executable')
    import original_inputs
    original_inputs.initialize(data)
names = json.loads((ROOT / 'source-export.json').read_text(encoding='utf-8'))['tests']
suite = unittest.defaultTestLoader.loadTestsFromNames(names)
result = unittest.TextTestRunner(verbosity=1).run(suite)
raise SystemExit(not result.wasSuccessful())
