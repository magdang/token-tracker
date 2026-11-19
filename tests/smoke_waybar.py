"""Bounded continuous-stream smoke test; does not touch credentials or desktop."""
import json
from pathlib import Path
import subprocess
import time

root = Path(__file__).resolve().parents[1]
process = subprocess.Popen([str(root / 'bin/token-tracker'), 'waybar', '--demo'],
                           stdout=subprocess.PIPE, text=True)
try:
    import select
    frames = []
    for _ in range(3):
        assert select.select([process.stdout], [], [], 7)[0], 'No JSON update within 7s'
        frames.append((time.monotonic(), json.loads(process.stdout.readline())))
    assert all(frame['text'] == 'AI DEMO' for _, frame in frames)
    assert all('sample data' in frame['tooltip'] for _, frame in frames)
    assert all(4.5 <= frames[i][0] - frames[i-1][0] <= 6.5 for i in (1, 2))
    print('PASS: three labelled multi-account JSON frames at five-second intervals')
finally:
    process.terminate()
    process.wait(timeout=3)
