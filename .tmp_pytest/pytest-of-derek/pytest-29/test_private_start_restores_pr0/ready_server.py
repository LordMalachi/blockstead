from pathlib import Path
import sys
raw = Path('server.properties').read_text(encoding='utf-8')
Path(sys.argv[1]).write_text(raw, encoding='utf-8')
values = dict(line.split('=', 1) for line in raw.splitlines() if '=' in line and not line.startswith('#'))
Path(values['level-name']).mkdir()
print('[Server thread/INFO]: validation boot', flush=True)
print('[Server thread/INFO]: Done (0.123s)!', flush=True)
for line in sys.stdin:
    if line.strip() == 'stop':
        raise SystemExit(0)
