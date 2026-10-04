"""Compose a 1080p pitch from authentic browser footage, original graphics and local TTS."""
import json, math, subprocess, sys, textwrap
from pathlib import Path
import numpy as np
import soundfile as sf
from PIL import Image, ImageDraw, ImageFont

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'output/video'
FINAL=ROOT/'video'
W,H,FPS=1920,1080,30
BG='#0a100c'; MINT='#b5ed9a'; WHITE='#dbe6d4'; DIM='#819675'; AMBER='#e2bc75'; CORAL='#e9927d'; LINE='#33462b'
FONT='/usr/share/fonts/TTF/DejaVuSansMono.ttf'
BOLD='/usr/share/fonts/TTF/DejaVuSansMono-Bold.ttf'
SANS='/usr/share/fonts/TTF/DejaVuSans.ttf'
FONTS={}
def font(size,bold=False):
    key=(size,bold)
    if key not in FONTS: FONTS[key]=ImageFont.truetype(BOLD if bold else FONT,size)
    return FONTS[key]
def txt(d,xy,text,size=24,fill=WHITE,bold=False,anchor=None):
    d.text(xy,text,font=font(size,bold),fill=fill,anchor=anchor,spacing=18)
def cmd(args):
    subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-y',*map(str,args)],check=True)
def duration(path):
    return float(subprocess.check_output(['ffprobe','-v','error','-show_entries','format=duration','-of','csv=p=0',str(path)]))
def logo(d,x,y,scale=1,color=MINT):
    for col,row in [(0,0),(1,0),(2,0),(0,1),(1,1),(1,2),(2,2)]:
        x1=x+col*15*scale;y1=y+row*15*scale
        d.rectangle((x1,y1,x1+10*scale,y1+10*scale),fill=color)
def frame_base(t,duration):
    im=Image.new('RGB',(W,H),BG);d=ImageDraw.Draw(im)
    for x in range(48,W,32):
        for y in range(48,990,32): d.point((x,y),fill='#1f2c20')
    d.line((96,80,1824,80),fill=LINE,width=1)
    d.line((96,962,1824,962),fill=LINE,width=1)
    logo(d,96,25,.7)
    txt(d,(145,27),'TRIPLENS / INCIDENT INTELLIGENCE',16,MINT)
    txt(d,(1824,27),'EVIDENCE BEFORE INFERENCE',14,DIM,anchor='ra')
    d.line((96,963,96+int(1728*t/duration),963),fill=MINT,width=2)
    return im,d

def opening(t,length):
    im,d=frame_base(t,length)
    txt(d,(128,136),'INCIDENT 101  /  COOLING-VALVE DISTURBANCE',18,DIM)
    txt(d,(128,230),'312 alarm events.',80,CORAL,True)
    txt(d,(128,365),'Where did it start?',74,WHITE,True)
    n=min(len('Trace the cascade. Find the first cause.'),int(max(0,t-.9)*28))
    txt(d,(133,494),'Trace the cascade. Find the first cause.'[:n],25,DIM)
    # Animated alarm marks: a visual index of the 312 computed events.
    for i in range(156):
        col=i%20;row=i//20
        active=i<int(min(1,t/2)*156)
        color=[MINT,AMBER,CORAL][min(2,row//3)] if active else '#253021'
        d.rectangle((1245+col*23,210+row*28,1253+col*23,221+row*28),fill=color)
    txt(d,(1245,510),'ONE FAULT. MANY CONSEQUENCES.',15,DIM)
    ratio=1-(1-min(1,t/1.7))**3
    for x,value,label,c in [(128,312,'RAW ALARM EVENTS',CORAL),(740,6,'UNIQUE CONDITIONS',AMBER),(1352,3,'PROCESS GROUPS',MINT)]:
        d.line((x,634,x+440,634),fill=LINE,width=1)
        txt(d,(x,673),str(round(value*ratio)),96,c)
        txt(d,(x,802),label,20,DIM)
    return im

def architecture(t,length):
    im,d=frame_base(t,length)
    txt(d,(128,128),'IMPLEMENTED INTERFACE / PROVIDER CONNECTION PENDING',17,AMBER)
    txt(d,(128,197),'Evidence first.',67,WHITE,True)
    txt(d,(128,280),'Structured reasoning next.',55,MINT)
    boxes=[(128,430,575,660),(727,430,1160,660),(1312,430,1792,660)]
    for i,(x1,y1,x2,y2) in enumerate(boxes):
        d.rectangle((x1,y1,x2,y2),fill='#141e12',outline=LINE,width=2)
        d.line((x1,y1,x1+70,y1),fill=MINT if i<2 else AMBER,width=3)
    txt(d,(157,465),'01 / NUMERICAL ENGINE',17,MINT)
    txt(d,(157,512),'Native Python',30,WHITE,True)
    txt(d,(157,569),'18 signals · 12 fault families',19,DIM)
    txt(d,(157,606),'1,547 branches per incident',18,DIM)
    txt(d,(757,465),'02 / EVIDENCE CONTRACT',17,MINT)
    txt(d,(757,512),'Structured JSON',29,WHITE,True)
    txt(d,(757,569),'Schema-validated response',18,DIM)
    txt(d,(757,606),'Validated tool requests',18,DIM)
    txt(d,(1342,465),'03 / PREPARED INFERENCE PATH',15,AMBER)
    txt(d,(1342,512),'NVIDIA Nemotron',28,WHITE,True)
    txt(d,(1342,569),'via Nebius Token Factory',18,DIM)
    txt(d,(1342,606),'LIVE INTEGRATION PENDING',16,AMBER)
    for x1,x2,pending in [(575,727,False),(1160,1312,True)]:
        for x in range(x1+12,x2-12,12): d.line((x,545,x+5,545),fill=DIM,width=2)
        if not pending:
            dot=x1+15+((t*.35)%1)*(x2-x1-30)
            d.ellipse((dot-4,541,dot+4,549),fill=MINT)
        d.line((x2-24,539,x2-16,545,x2-24,551),fill=DIM,width=2)
    txt(d,(128,738),'The investigator works with evidence.',28,WHITE)
    txt(d,(128,786),'The process engine computes the numbers.',28,DIM)
    txt(d,(128,881),'CURRENT RECORDING  /  LOCAL INVESTIGATION POLICY',16,AMBER)
    return im

def closing(t,length):
    im,d=frame_base(t,length)
    txt(d,(960,184),'DETECT → INVESTIGATE → VERIFY → INTERVENE → LEARN',24,DIM,anchor='ma')
    logo(d,690,305,1.9)
    txt(d,(807,302),'triplens',95,MINT,True)
    txt(d,(960,491),'Follow the evidence.',58,WHITE,True,anchor='ma')
    txt(d,(960,604),'Change the outcome.',42,DIM,anchor='ma')
    txt(d,(960,653),'Incident intelligence for process engineers.',23,DIM,anchor='ma')
    d.rectangle((480,791,1440,872),fill='#162112',outline=LINE,width=1)
    txt(d,(960,815),'github.com/dongxuelian2/L5',28,MINT,anchor='ma')
    return im

def ass_time(sec):
    cent=round(sec*100);h,rem=divmod(cent,360000);m,rem=divmod(rem,6000);s,c=divmod(rem,100)
    return f'{h}:{m:02}:{s:02}.{c:02}'
def srt_time(sec):
    millis=round(sec*1000);h,rem=divmod(millis,3600000);m,rem=divmod(rem,60000);s,ms=divmod(rem,1000)
    return f'{h:02}:{m:02}:{s:02},{ms:03}'
def ass_header():
    return '''[Script Info]
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080
WrapStyle: 2
[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Caption,DejaVu Sans,30,&H00E7EDE0,&H00E7EDE0,&H00081008,&H00081008,0,0,0,0,100,100,0,0,1,1,0,2,115,115,18,1
Style: Chapter,DejaVu Sans Mono,14,&H009AEDB5,&H009AEDB5,&H00081008,&H00081008,0,0,0,0,100,100,1,0,1,0,0,7,132,132,6,1
[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
'''

def main():
    scenes=json.loads((OUT/'timings.json').read_text())
    expected=json.loads((FINAL/'scenes.json').read_text())
    if [s['id'] for s in scenes] != [s['id'] for s in expected]:
        raise ValueError('Narration timings do not match the current edit.')
    if sum(s['duration'] for s in scenes)>=180: raise ValueError('Video must stay under 3 minutes.')
    edits={s['id']:s for s in expected}
    selected=set(sys.argv[1:])
    if selected-set(edits): raise ValueError('Unknown scene ID.')
    (OUT/'clips').mkdir(parents=True,exist_ok=True)
    srt=[];offset=0;index=0
    for scene in scenes:
        name=scene['id'];length=scene['duration'];kind=scene['kind']
        ass=ass_header()
        for cue in scene['cues']:
            wrapped='\\N'.join(textwrap.wrap(cue['text'],width=98))
            ass+=f"Dialogue: 1,{ass_time(cue['start'])},{ass_time(cue['end']+.1)},Caption,,0,0,0,,{{\\fad(90,110)}}{wrapped}\n"
            index+=1
            srt.append(f"{index}\n{srt_time(offset+cue['start'])} --> {srt_time(offset+cue['end'])}\n"+'\n'.join(textwrap.wrap(cue['text'],width=95))+'\n')
        if kind=='capture': ass+=f"Dialogue: 2,0:00:00.00,{ass_time(length)},Chapter,,0,0,0,,{scene['chapter']}    /    {scene['title']}\n"
        ass_path=OUT/f'{name}.ass';ass_path.write_text(ass)
        target=OUT/'clips'/f'{name}.mp4'
        if selected and name not in selected:
            if not target.exists(): raise FileNotFoundError(f'Render all scenes first: {target}')
            offset+=length
            continue
        if kind=='capture':
            source=ROOT/'output/playwright/video-v2'/f'{name}.webm'
            # Fit each complete take to its editorial slot, preserving actual UI interactions.
            factor=length/duration(source)
            lead_trim=edits[name].get('take_lead_trim_seconds',0)
            # Remove CLI startup idle time and hold the last recorded frame instead.
            # The actual interactions, numbers and their order are preserved.
            vf=f'trim=start={lead_trim},setpts={factor:.8f}*(PTS-STARTPTS),tpad=stop_mode=clone:stop_duration={lead_trim*factor:.8f},fps={FPS},scale=1656:920:flags=lanczos,pad=1920:1080:132:32:color={BG},drawbox=x=131:y=31:w=1658:h=922:color=0x33462b:t=1'
            cmd(['-i',source,'-i',OUT/'audio'/f'{name}.wav','-vf',vf+f",ass={ass_path},fade=t=in:d=0.25,fade=t=out:st={length-.3}:d=0.3",'-af','afade=t=in:d=0.1,afade=t=out:st='+str(length-.15)+':d=0.15','-t',length,'-c:v','libx264','-threads','4','-preset','fast','-crf','19','-pix_fmt','yuv420p','-c:a','aac','-b:a','192k',target])
        else:
            render={'opening':opening,'architecture':architecture,'closing':closing}[kind]
            args=['ffmpeg','-hide_banner','-loglevel','error','-y','-f','rawvideo','-pixel_format','rgb24','-video_size','1920x1080','-framerate',str(FPS),'-i','pipe:0','-i',str(OUT/'audio'/f'{name}.wav'),'-vf',f'ass={ass_path},fade=t=in:d=0.35,fade=t=out:st={length-.35}:d=0.35','-c:v','libx264','-threads','4','-preset','fast','-crf','19','-pix_fmt','yuv420p','-c:a','aac','-b:a','192k','-t',str(length),str(target)]
            p=subprocess.Popen(args,stdin=subprocess.PIPE)
            for frame in range(round(length*FPS)):
                p.stdin.write(render(frame/FPS,length).tobytes())
            p.stdin.close()
            if p.wait(): raise RuntimeError('Card encoding failed')
        print('Rendered',name,flush=True);offset+=length
    (FINAL/'triplens-pitch.en.srt').write_text('\n'.join(srt))
    manifest=OUT/'concat.txt';manifest.write_text('\n'.join(f"file '{OUT/'clips'/ (s['id']+'.mp4')}'" for s in scenes))
    cmd(['-f','concat','-safe','0','-i',manifest,'-c','copy',OUT/'assembled.mp4'])
    # An original quiet tonal bed, synthesized here; no third-party music or samples.
    rate=48000;t=np.arange(int(offset*rate),dtype=np.float64)/rate
    bed=np.zeros_like(t)
    for frequency,level in [(110,.008),(164.8138,.005),(220,.004),(261.6256,.003)]:
        bed+=np.sin(2*np.pi*frequency*t+.025*np.sin(2*np.pi*.11*t))*level*(.6+.4*np.sin(2*np.pi*.045*t)**2)
    envelope=np.minimum(1,t/2)*np.minimum(1,(offset-t)/3)
    bed*=envelope
    sf.write(OUT/'original-bed.wav',bed,rate)
    final=FINAL/'triplens-pitch.mp4'
    cmd(['-i',OUT/'assembled.mp4','-i',OUT/'original-bed.wav','-filter_complex','[0:a]loudnorm=I=-16:TP=-1.5:LRA=7[voice];[voice][1:a]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.94[a]','-map','0:v','-map','[a]','-c:v','copy','-c:a','aac','-b:a','192k','-ar','48000','-movflags','+faststart','-metadata','title=TripLens — Follow the evidence. Change the outcome.','-metadata','comment=Browser footage and generated process results. English synthetic narration. Live Nebius integration pending.',final])
    print('COMPLETE',final,'duration',duration(final),flush=True)

if __name__=='__main__': main()
