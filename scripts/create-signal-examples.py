"""Reproduce the three synthetic CSV sources used for Signal Workspace validation."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import math

folder = Path(__file__).resolve().parents[1] / 'examples' / 'data-foundation'
folder.mkdir(parents=True, exist_ok=True)
origin = datetime(2026, 10, 24, 8, tzinfo=timezone(timedelta(hours=8)))

temperature = ['timestamp,temp_C']
for t in range(600):
    value = '' if t == 290 else f'{80 + .2*math.sin(t/9) + (8 if 380 <= t < 435 else 0):.6f}'
    temperature.append(f'{(origin+timedelta(seconds=t)).isoformat()},{value}')

flow = ['timestamp,flow_m3h']
for t in range(0, 521, 2):
    value = '' if t in (302, 304) else f'{12 + .3*math.sin(t/15) - (2 if 390 <= t < 440 else 0):.6f}'
    flow.append(f'{int((origin.timestamp()+t)*1000)},{value}')

pressure = ['seconds,pressure_kpa']
t, i = 0., 0
while t <= 540:
    if not 220 < t < 280:
        value = '' if 168 <= t <= 171 else f'{300 + 2*math.sin(t/12) + (15 if 365 <= t < 410 else 0):.6f}'
        pressure.append(f'{t:.1f},{value}')
        if i == 30:
            pressure.append(f'{t:.1f},301.000000')
        if i == 100:
            pressure.append('invalid-time,302.000000')
    t = round(t + (1, .8, 1.3)[i % 3], 1)
    i += 1

for name, rows in [('temperature-1s.csv', temperature), ('flow-2s-unix-ms.csv', flow), ('pressure-irregular.csv', pressure)]:
    (folder / name).write_text('\n'.join(rows) + '\n', encoding='utf-8')
    print(f'{name}: {len(rows)-1} source rows')
