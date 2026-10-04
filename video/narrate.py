"""Produce local English narration and exact sentence-level subtitle timings."""
import json
import hashlib
import os
from pathlib import Path
import numpy as np
import soundfile as sf
import onnxruntime as ort
from kokoro_onnx import Kokoro

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'output/video'
SCENES = json.loads((ROOT / 'video/scenes.json').read_text())
os.environ.setdefault('OMP_NUM_THREADS', '4')
options = ort.SessionOptions()
options.intra_op_num_threads = 4
options.inter_op_num_threads = 1
session = ort.InferenceSession(str(OUT / 'models/kokoro-v1.0.onnx'), sess_options=options, providers=['CPUExecutionProvider'])
kokoro = Kokoro.from_session(session, str(OUT / 'models/voices-v1.0.bin'))
metadata = []
for scene in SCENES:
    sections=[]
    durations=[]
    for i, line in enumerate(scene['lines']):
        digest=hashlib.sha256(line.encode()).hexdigest()[:10]
        path=OUT / 'audio' / f"{scene['id']}-{i}-{digest}.wav"
        if path.exists():
            samples, sr = sf.read(path)
        else:
            samples, sr = kokoro.create(line, voice='af_heart', speed=1.0, lang='en-us')
            # Remove long trailing silence, retaining breaths and natural sentence ends.
            active=np.flatnonzero(np.abs(samples)>0.004)
            if len(active):
                samples=samples[max(0, active[0]-int(.07*sr)):min(len(samples),active[-1]+int(.16*sr))]
            sf.write(path,samples,sr)
        sections.append(samples)
        durations.append(len(samples)/sr)
    spoken=sum(durations)
    minimum=spoken+.55+.3*(len(sections)-1)+.55
    if minimum>scene['duration']:
        raise ValueError(f"{scene['id']}: speech requires {minimum:.2f}s, allocated {scene['duration']}s")
    # Spread sentence breaks, leaving a short opening and a visual hold at the end.
    gap=min(.9,max(.3,(scene['duration']-spoken-1.5)/max(1,len(sections)-1)))
    track=np.zeros(int(scene['duration']*sr),dtype=np.float32)
    cursor=.5
    cues=[]
    for line, samples, duration in zip(scene['lines'], sections, durations):
        start=int(cursor*sr)
        track[start:start+len(samples)] = samples
        cues.append({'start':round(cursor,3),'end':round(cursor+duration,3),'text':line})
        cursor+=duration+gap
    sf.write(OUT/'audio'/f"{scene['id']}.wav",track,sr)
    metadata.append({**scene,'spoken':spoken,'cues':cues})
    print(f"{scene['id']}: {spoken:.2f}s speech / {scene['duration']}s scene",flush=True)
(OUT/'timings.json').write_text(json.dumps(metadata,indent=2))
