# TripLens product video / 项目展示视频

[Watch / download MP4](triplens-pitch.mp4) · [English subtitles](triplens-pitch.en.srt) · [中文字幕](triplens-pitch.zh-CN.srt)

**2:50 · 1920×1080 · 30 fps · H.264 / AAC · English narration and burned-in English captions.**

视频录制了 v0.2 的实际浏览器操作：多证据调查、冻结传感器、报警压缩、逐秒干预搜索、工具审计、RCA 导出和事故记忆。录屏没有替换页面响应或修改计算数据。剪辑对真实录制片段做了时间调整；片头、架构卡和片尾是另行制作的图形。

The recording shows actual v0.2 browser interactions. Recorded takes are edited to fit the narration; numerical results and application responses are not replaced. The title, architecture and closing cards are original graphics. Narration is synthetic English speech, using the `af_heart` voice; it does not represent a named person. The quiet background bed is synthesized by the rendering script, with no sampled third-party music.

成片检查：完整解码通过；5,100 帧；无持续 0.5 秒以上的黑场；中英文各 30 条字幕，时间轴一致。关键干预画面与旁白已逐帧抽查。

Final checks: full FFmpeg decode succeeded; 5,100 frames; no black segment lasting 0.5 seconds or longer; 30 matching English and Chinese subtitle cues. Sampled frames verify the +101s / +102s intervention transition against narration. Audio sample peak is −0.8 dBFS.

## Chapters

| Time | Content |
|---|---|
| 00:00 | The problem: 312 alarm events |
| 00:09 | 18 channels, two controllers, 12 incident sessions |
| 00:23 | Competing hypotheses and evidence available at each moment |
| 00:44 | Frozen pressure sensor and independent measurements |
| 01:00 | 312 events → 6 conditions → 3 process groups |
| 01:14 | 1,547 intervention branches; +101s versus +102s |
| 01:43 | Structured tool audit and RCA export |
| 02:02 | Incident memory, regression matrix and alarm improvement |
| 02:23 | Numerical engine and prepared model interface |
| 02:40 | Closing |

## Submission status / 参赛前待办

视频采用英文旁白、英文字幕和实际运行画面，时长低于三分钟。比赛要求公开视频链接；此文件尚未上传 YouTube 或提交 Devpost。规则还要求项目实际在 Nebius 上运行并使用 NVIDIA 开源模型，当前版本仍采用本地调查策略，不能将预留接口视为已完成真实接入。正式提交前需要完成并验证接入，再替换 02:23 的接口说明片段。[Official rules](https://nebiusglobalaihackathon.devpost.com/rules)

The competition asks for a public video under three minutes and actual running footage. The MP4 has not been uploaded to YouTube or submitted to Devpost. The application still needs verified runtime use of Nebius and an NVIDIA open-source model before it satisfies that technical requirement. The 02:23 architecture segment accurately identifies the current integration status. Organizers also recommend naming the platform and model audibly and presenting the video as a pitch.[Submission guidance](https://nebiusglobalaihackathon.devpost.com/updates/46205-how-to-build-a-winning-project)

## Rebuilding the edit

The app itself still has no new runtime dependencies. Video production uses separate optional tools:

- Python 3.12, `kokoro-onnx==0.6.1`, `onnxruntime==1.30.0`, `numpy`, `soundfile`, `Pillow`, `espeakng-loader`.
- FFmpeg / FFprobe with libx264, AAC and libass.
- Playwright CLI and Chromium; viewport **1440×800**, recording **30 fps** with cursor.
- System DejaVu Sans / DejaVu Sans Mono fonts; change the paths in `render.py` on another platform.

Local production assets live under ignored `output/video/`; raw recordings live under ignored `output/playwright/video-v2/`. Model weights and the virtual environment are intentionally outside Git.

1. Build and serve the project at `http://127.0.0.1:8787`.
2. Place the Kokoro ONNX model at `output/video/models/kokoro-v1.0.onnx` and voices at `output/video/models/voices-v1.0.bin`.
3. Create `output/video/audio/` and run `python video/narrate.py`. It caches each sentence by text hash and emits exact subtitle timing data.
4. Open Playwright CLI session `triplens-pitch-v2` at the application, with a 1440×800 viewport. Set `PLAYWRIGHT_CLI` if using an installed CLI instead of `npx`.
5. Run `python video/capture.py` to record the actual UI, or supply scene IDs to retake individual scenes.
6. Run `python video/render.py` to compose the MP4 and English SRT. Scene durations are checked against the three-minute limit. After a full render, pass scene IDs to rerender selected clips and reassemble the edit. `take_lead_trim_seconds` removes idle time at the start of a take and holds its final recorded frame; recalibrate that setting when retaking footage.

Sources: [Kokoro ONNX](https://github.com/thewh1teagle/kokoro-onnx) (MIT), [Kokoro-82M](https://huggingface.co/hexgrad/Kokoro-82M) (Apache-2.0 model). These are video narration tools, not the incident investigation model.
