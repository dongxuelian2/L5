"""Record actual browser interactions via Playwright CLI, with reproducible takes.

Start the Python server, open the named Playwright session using the video config,
then run this script. No incident state, scores or application responses are edited.
"""
import os
import shlex
import subprocess
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
CLI=shlex.split(os.environ.get('PLAYWRIGHT_CLI','npx --yes --package @playwright/cli playwright-cli'))
SESSION='triplens-pitch-v2'
OUT=ROOT/'output/playwright/video-v2'
OUT.mkdir(parents=True,exist_ok=True)

def cli(*args):
    result=subprocess.run(CLI+[f'-s={SESSION}',*args],cwd=ROOT,capture_output=True,text=True)
    if result.returncode or '### Error' in result.stdout:
        raise RuntimeError(result.stdout+'\n'+result.stderr)
    print(result.stdout[:800],flush=True)

def code(body):cli('run-code',f'async (page) => {{ {body} }}')
def record(name,prepare,actions):
    print('Preparing',name,flush=True)
    code(prepare)
    cli('snapshot','--filename',f'output/playwright/video-v2/{name}-before.yml')
    cli('video-start',f'output/playwright/video-v2/{name}.webm','--size','1440x800','--fps','30','--cursor')
    try:code(actions)
    finally:cli('video-stop')
    print('Recorded',name,flush=True)

BASE='await page.getByRole("button",{name:"Investigate",exact:true}).click(); await page.getByRole("combobox",{name:"Incident session"}).selectOption("INC-101"); await page.getByRole("button",{name:"+240s",exact:true}).click(); await page.getByRole("tab",{name:"⌘ Evidence",exact:true}).click(); '
SETTLE='await page.mouse.move(220,75); await page.waitForTimeout(700);'
SCENES={
'02-overview':(
    BASE+'await page.evaluate(()=>window.scrollTo(0,0));'+SETTLE,
    'await page.waitForTimeout(4800); await page.evaluate(()=>window.scrollTo({top:380,behavior:"smooth"})); await page.waitForTimeout(3500); await page.getByRole("button",{name:"Inspect CV-101",exact:true}).hover(); await page.waitForTimeout(4400);'),
'03-investigate':(
    BASE+'await page.evaluate(()=>window.scrollTo(0,850));'+SETTLE,
    'await page.waitForTimeout(5200); await page.evaluate(()=>window.scrollTo({top:400,behavior:"smooth"})); await page.waitForTimeout(2800); await page.getByRole("button",{name:"02 Reaction-rate disturbance 75 / 100",exact:true}).click(); await page.waitForTimeout(4600); await page.getByRole("button",{name:"+40s",exact:true}).click(); await page.waitForTimeout(2700); await page.getByRole("button",{name:"+70s",exact:true}).click(); await page.waitForTimeout(2100); await page.getByRole("button",{name:"+240s",exact:true}).click(); await page.waitForTimeout(1500);'),
'04-sensor':(
    BASE+'await page.getByRole("combobox",{name:"Incident session"}).selectOption("INC-110"); await page.getByRole("button",{name:"Inspect PI-101",exact:true}).click(); await page.evaluate(()=>window.scrollTo(0,390));'+SETTLE,
    'await page.waitForTimeout(4500); await page.getByRole("button",{name:"PI-102 ·",exact:true}).click(); await page.evaluate(()=>window.scrollTo({top:930,behavior:"smooth"})); await page.waitForTimeout(3100); await page.getByRole("button",{name:"PI-101 !",exact:true}).click(); await page.evaluate(()=>window.scrollTo({top:930,behavior:"smooth"})); await page.waitForTimeout(7000);'),
'05-alarm':(
    BASE+'await page.getByRole("tab",{name:"≋ Alarm journal",exact:true}).click(); await page.getByRole("heading",{name:"Flood compression",exact:true}).waitFor(); await page.evaluate(()=>window.scrollTo(0,350));'+SETTLE,
    'await page.waitForTimeout(4800); await page.getByRole("button",{name:"activation",exact:true}).click(); await page.waitForTimeout(3400); await page.getByRole("button",{name:"reannunciation",exact:true}).click(); await page.waitForTimeout(4800);'),
'06-recovery':(
    BASE+'await page.getByRole("tab",{name:"⑂ Interventions",exact:true}).click(); await page.getByRole("heading",{name:"Recovery envelope",exact:true}).waitFor(); await page.evaluate(()=>window.scrollTo(0,470));'+SETTLE,
    'await page.waitForTimeout(7500); const slider=page.getByRole("slider"); await slider.focus(); for(let i=0;i<11;i++){await slider.press("ArrowRight"); await page.waitForTimeout(150);} await page.mouse.move(1130,500); await page.waitForTimeout(7400); await slider.press("ArrowRight"); await page.waitForTimeout(3300); await page.getByRole("button",{name:"⑂ Emergency cooling Latest recovery +103s",exact:true}).click(); await page.waitForTimeout(3200); await page.getByRole("button",{name:"× Start backup pump Severity 1/5 · utility weight 2 —",exact:true}).click(); await page.waitForTimeout(3300);'),
'07-audit':(
    BASE+'await page.getByRole("tab",{name:"≡ Tool audit",exact:true}).click(); await page.getByText("inspect_controller",{exact:true}).waitFor(); await page.evaluate(()=>window.scrollTo(0,400));'+SETTLE,
    'await page.waitForTimeout(2000); await page.getByText("inspect_controller",{exact:true}).click(); await page.waitForTimeout(5000); await page.getByText("inspect_controller",{exact:true}).click(); await page.getByText("compare_hypotheses",{exact:true}).click(); await page.waitForTimeout(4300); await page.evaluate(()=>window.scrollTo({top:0,behavior:"smooth"})); await page.waitForTimeout(1300); await page.getByRole("button",{name:"RCA .md ↓",exact:true}).click(); await page.waitForTimeout(2400);'),
'08-learn':(
    BASE+'await page.getByRole("textbox",{name:"Operator review note",exact:true}).fill("Inspect CV-101 linkage before return to service."); await page.getByRole("button",{name:"Save to memory ↗",exact:true}).scrollIntoViewIfNeeded();'+SETTLE,
    'await page.waitForTimeout(800); await page.getByRole("button",{name:"Save to memory ↗",exact:true}).click(); await page.waitForTimeout(1200); await page.getByRole("button",{name:"Learn",exact:true}).click(); await page.waitForTimeout(4300); await page.evaluate(()=>window.scrollTo({top:560,behavior:"smooth"})); await page.waitForTimeout(6300); await page.evaluate(()=>window.scrollTo({top:1020,behavior:"smooth"})); await page.waitForTimeout(5200);')
}
for name in sys.argv[1:] or SCENES:record(name,*SCENES[name])
