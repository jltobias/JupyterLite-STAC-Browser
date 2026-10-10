"""Archive integrity remains enforced when Python assertions are optimized out."""
from pathlib import Path
import subprocess
import sys
import unittest


class RasterVendorTests(unittest.TestCase):
    def test_integrity_mismatch_under_optimized_python(self):
        code = '''
from unittest.mock import patch
from scripts.vendor_raster import archive
with patch('scripts.vendor_raster.get', return_value=b'incorrect archive'):
    try:
        archive('https://example.test/archive.tgz', 'sha512-bad')
    except ValueError as error:
        if 'integrity mismatch' not in str(error):
            raise
    else:
        raise RuntimeError('Invalid archive accepted')
'''
        subprocess.run([sys.executable, '-O', '-c', code],
                       cwd=Path(__file__).resolve().parents[1], check=True)


if __name__ == '__main__':
    unittest.main()
