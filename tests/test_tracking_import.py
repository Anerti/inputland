import subprocess
import sys

CODE = """
import resource
before = resource.getrlimit(resource.RLIMIT_RTTIME)
import inputland.tracking
after = resource.getrlimit(resource.RLIMIT_RTTIME)
assert after == before, f"RLIMIT_RTTIME changed from {before} to {after}"
"""


def test_importing_tracking_keeps_realtime_limit():
    result = subprocess.run([sys.executable, "-c", CODE], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr[-500:]
