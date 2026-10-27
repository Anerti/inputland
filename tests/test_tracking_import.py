import subprocess
import sys

# Regression: MediaPipe's sounddevice import loaded PipeWire's JACK client, which set
# RLIMIT_RTTIME to 0, and the kernel SIGKILLed the process while creating the tracker.
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
