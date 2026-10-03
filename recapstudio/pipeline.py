"""End-to-end orchestration: analyst → voice → subtitles → render.

Progress is reported through :class:`JobStore` on fixed stage boundaries so a
long render shows "which step, how much is left" instead of a frozen bar.
"""
from __future__ import annotations

import math
import os
import shutil
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Optional

from . import config
from .ai import extract_timeline
from .jobs import JobCancelled, JobStore, StageProgress
from .media import get_media_duration, get_video_info, run_ffmpeg
from .render import export_srt, render_master
from .subtitles import build_ass
from .tts import VOICE_CATALOG, master_audio, tts_engine
from .util import (ensure_disk_space, get_logger, human_bytes, human_time,
                   safe_rmtree)

log = get_logger("recap.pipeline")

STAGE_BOUNDS = {
    "prepare": (0.0, 4.0),
    "analyze": (4.0, 46.0),
    "coverage": (46.0, 58.0),
    "voice": (58.0, 82.0),
    "mix": (82.0, 86.0),
    "subtitles": (86.0, 89.0),
    "render": (89.0, 98.0),
    "finalize": (98.0, 100.0),
}


def _voice_config(language: str, voice_key: str) -> dict[str, str]:
    catalog = VOICE_CATALOG.get(language) or VOICE_CATALOG["my"]
    return catalog.get(voice_key) or next(iter(catalog.values()))


def _job_workdir(job_id: str) -> Path:
    path = config.TMP_DIR / job_id
    path.mkdir(parents=True, exist_ok=True)
    return path


class RecapPipeline:
    def __init__(self, store: JobStore):
        self.store = store

    # ── helpers ────────────────────────────────────────────────────────
    def _stage(self, job_id: str, stage: str, message: str = "") -> StageProgress:
        start, end = STAGE_BOUNDS.get(stage, (0.0, 100.0))
        return StageProgress(self.store, job_id, stage, start, end, message)

    def _cancel(self, job_id: str):
        return lambda: self.store.is_cancelled(job_id)

    # ── main entry ─────────────────────────────────────────────────────
    def run_recap(self, job_id: str, payload: dict[str, Any]) -> None:
        store = self.store
        job = store.get(job_id)
        if job is None:
            return
        work_dir = _job_workdir(job_id)
        try:
            store.update(job_id, status="running", stage="prepare", progress=1,
                         message="ဗီဒီယို ဖိုင် စစ်ဆေးနေပါသည်...")
            store.log(job_id, f"Job started • payload keys: {sorted(payload.keys())}")

            input_video = str(config.resolve(payload.get("input_video", "")))
            if not Path(input_video).exists():
                raise FileNotFoundError(
                    "တင်ထားသော ဗီဒီယိုဖိုင် ရှာမတွေ့ပါ (server restart ဖြစ်သွားနိုင်ပါသည်)။ "
                    "ဗီဒီယိုကို ပြန်တင်ပေးပါ။"
                )
            info = get_video_info(input_video)
            duration = info["duration"]
            if duration <= 0.5:
                raise ValueError("ဗီဒီယို ကြာချိန် ဖတ်၍ မရပါ - ဖိုင် ပျက်နေနိုင်ပါသည်။")

            quality = payload.get("quality", "balanced")
            ensure_disk_space(int(info["size"] * 2.5) + 200 * 1024 * 1024)
            store.update(job_id, duration=duration, input_video=config.rel(input_video),
                         stats={"input": {"duration": duration, "width": info["width"],
                                          "height": info["height"], "size": info["size"],
                                          "has_audio": info["has_audio"]}},
                         message=f"✅ ဗီဒီယို အဆင်သင့် ({human_time(duration)} • "
                                 f"{info['width']}x{info['height']} • {human_bytes(info['size'])})")
            store.log(job_id, f"Input OK: {duration:.2f}s {info['width']}x{info['height']} "
                              f"{human_bytes(info['size'])} audio={info['has_audio']}")

            # ── 1. AI timeline ────────────────────────────────────────
            api_key = (payload.get("api_key") or "").strip()
            fill_mode = payload.get("fill_mode", "continuous")
            analyze_prog = self._stage(job_id, "analyze")
            result = extract_timeline(
                api_key=api_key,
                video_path=input_video,
                duration=duration,
                language=payload.get("lang", "my"),
                mode=payload.get("mode", "auto"),
                fill_mode=fill_mode,
                model=payload.get("model"),
                progress=analyze_prog,
                cancel=self._cancel(job_id),
                log_fn=lambda msg: store.log(job_id, msg),
            )
            dialogues = result["dialogues"]
            if not dialogues:
                raise ValueError(
                    "AI မှ စကားပြောခန်း ရှာမတွေ့ပါ။ ဗီဒီယိုတွင် စကားပြောခန်း မပါဝင်နိုင်ပါ "
                    "သို့မဟုတ် AI model ကို ပြောင်း၍ ပြန်စမ်းပါ။"
                )
            coverage = result.get("coverage", {})
            store.update(job_id, stage="coverage", progress=STAGE_BOUNDS["coverage"][1],
                         dialogues=dialogues,
                         hook_line1=result.get("hook_line1", ""),
                         hook_line2=result.get("hook_line2", ""),
                         coverage=coverage,
                         message=f"🧠 စကားပြောခန်း {len(dialogues)} ခု တွေ့ပါသည် "
                                 f"(coverage {coverage.get('coverage_percent', 0)}%)")
            store.log(job_id, f"AI timeline: {len(dialogues)} lines, "
                              f"coverage={coverage.get('coverage_percent')}%")
            self.store.raise_if_cancelled(job_id)

            # ── 2. voice ──────────────────────────────────────────────
            voice_cfg = _voice_config(payload.get("lang", "my"), payload.get("voice", "thiha"))
            store.update(job_id, stage="voice", message="🎙️ အသံ သွင်းနေပါသည်...")
            voice_prog = self._stage(job_id, "voice")

            def voice_cb(pct: float, message: str) -> None:
                voice_prog(pct, message)

            mix = tts_engine.build_narration(
                dialogues=dialogues,
                voice_cfg=voice_cfg,
                duration=duration,
                work_dir=work_dir,
                tag=job_id,
                progress=voice_cb,
                cancel=self._cancel(job_id),
            )
            voice_stats = mix.stats()
            store.update(job_id, stats={**job.stats, "voice": voice_stats},
                         message=f"🎧 အသံ {voice_stats['lines']} လိုင်း ပြီးပါပြီ")
            for warning in mix.warnings:
                store.log(job_id, f"⚠️ {warning}")
                store.update(job_id, stats={**store.get(job_id).stats})
            self.store.raise_if_cancelled(job_id)

            # ── 3. mix/master audio ───────────────────────────────────
            store.update(job_id, stage="mix", message="🧵 အသံ timeline တိကျစွာ ချိန်နေပါသည်...")
            narration_mp3 = work_dir / f"narration_{job_id}.mp3"
            master_audio(mix.audio_path, narration_mp3, duration,
                         loudnorm=config.settings.loudness_normalize,
                         bitrate=config.settings.audio_bitrate)
            narration_seconds = get_media_duration(narration_mp3)
            store.log(job_id, f"Narration mastered: {narration_seconds:.2f}s of {duration:.2f}s")
            store.update(job_id, progress=STAGE_BOUNDS["mix"][1])

            # ── 4. subtitles ──────────────────────────────────────────
            ass_path = None
            srt_path = None
            if payload.get("enable_subtitles", True):
                store.update(job_id, stage="subtitles", message="📝 စာတန်းထိုး ဖန်တီးနေပါသည်...")
                ass_path = str(work_dir / f"{job_id}.ass")
                target_w, target_h = self._target_size(payload, info)
                build_ass(
                    dialogues=dialogues, duration=duration, ass_path=ass_path,
                    hook_line1=payload.get("hook_line1", store.get(job_id).hook_line1) or "",
                    hook_line2=payload.get("hook_line2", store.get(job_id).hook_line2) or "",
                    font_size=int(payload.get("sub_font_size", 42)),
                    v_margin=int(target_h * (float(payload.get("sub_v_pos_percent", 22)) / 100.0)),
                    hex_color=payload.get("sub_color_hex", "#00F2FE"),
                    bg_style=payload.get("sub_bg_style", "Solid Box"),
                    play_res=(target_w, target_h),
                    hook_seconds=float(payload.get("hook_seconds", 0)),
                    subtitle_alpha=int(payload.get("sub_alpha", 0)),
                    uppercase_hook=bool(payload.get("hook_uppercase", False)),
                )
                srt_path = str(work_dir / f"{job_id}.srt")
                export_srt(dialogues, srt_path)
                store.update(job_id, progress=STAGE_BOUNDS["subtitles"][1])

            # ── 5. render ─────────────────────────────────────────────
            store.update(job_id, stage="render", message="🎬 Final Video Render စတင်နေပါသည်...")
            render_prog = self._stage(job_id, "render")
            output_name = f"recap_{job_id}.mp4"
            output_path = str(config.OUTPUT_DIR / output_name)
            logo_path = payload.get("logo_path")
            logo_pos = None
            if logo_path and payload.get("logo_pos_x") is not None and payload.get("logo_pos_y") is not None:
                logo_pos = (float(payload["logo_pos_x"]), float(payload["logo_pos_y"]))
            render_result = render_master(
                input_video=input_video,
                narration_wav=str(narration_mp3),
                output_video=output_path,
                ass_path=ass_path,
                logo_path=str(config.resolve(logo_path)) if logo_path else None,
                logo_pos=logo_pos,
                reframe=payload.get("reframe_mode", "Smart Blur Background"),
                mute_original=bool(payload.get("mute_original", True)),
                keep_original_level=float(payload.get("original_level", 0.12)),
                narration_gain=float(payload.get("narration_gain", 1.3)),
                quality=quality,
                target_size=self._target_size(payload, info),
                duration=duration,
                progress=render_prog,
                cancel=self._cancel(job_id),
            )

            # ── 6. finalize ───────────────────────────────────────────
            store.update(job_id, stage="finalize", message="💾 ဖိုင် သိမ်းဆည်းနေပါသည်...")
            final_size = os.path.getsize(output_path) if os.path.exists(output_path) else 0
            published = self._publish_extras(job_id, output_path, ass_path, srt_path, narration_mp3)
            stats = {
                **(store.get(job_id).stats or {}),
                "output": {
                    "size": final_size,
                    "duration": render_result.get("duration", duration),
                    "burned_subtitles": render_result.get("burned_subtitles", False),
                    "fast_path": render_result.get("fast_path", False),
                },
            }
            warnings = list(render_result.get("warnings", [])) + list(mix.warnings)
            if warnings:
                stats["warnings"] = warnings
            store.update(job_id,
                         status="completed", progress=100, stage="finalize",
                         output_video=config.rel(output_path),
                         download_url=f"/api/download/{output_name}",
                         preview_url=f"/api/asset?path={config.rel(output_path)}",
                         stats=stats, **published,
                         message=f"🎉 ဗီဒီယို အောင်မြင်စွာ ပြီးပါပြီ ({human_bytes(final_size)})")
            store.log(job_id, f"DONE → {output_name} ({human_bytes(final_size)}) in "
                              f"{human_time(store.get(job_id).elapsed_seconds())}")
            safe_rmtree(work_dir)

        except JobCancelled:
            store.update(job_id, status="cancelled", message="⏹️ အလုပ်ကို ရပ်တန့်လိုက်ပါပြီ")
            store.log(job_id, "cancelled by user")
            safe_rmtree(work_dir)
        except Exception as exc:  # noqa: BLE001 - surface everything to the UI
            log.exception("recap job %s failed", job_id)
            message = str(exc)
            if len(message) > 900:
                message = message[:400] + " … " + message[-400:]
            store.update(job_id, status="failed", error=message,
                         message=f"❌ {message}")
            store.log(job_id, f"FAILED: {message}")
            safe_rmtree(work_dir)

    # ── re-render with edited timeline ─────────────────────────────────
    def run_rerender(self, job_id: str, payload: dict[str, Any]) -> None:
        store = self.store
        job = store.get(job_id)
        if job is None:
            return
        try:
            dialogues = payload.get("dialogues") or job.dialogues or []
            dialogues = [
                {"start": float(d.get("start", 0)), "end": float(d.get("end", 0)),
                 "text": str(d.get("text", "")), "speaker": str(d.get("speaker", ""))}
                for d in dialogues if str(d.get("text", "")).strip()
            ]
            if not dialogues:
                raise ValueError("Timeline တွင် စာသား မရှိပါ - အနည်းဆုံး လိုင်းတစ်ခု ထည့်ပါ။")
            input_video = str(config.resolve(job.input_video))
            duration = get_media_duration(input_video) or job.duration
            info = get_video_info(input_video)
            work_dir = _job_workdir(job_id)
            ensure_disk_space(300 * 1024 * 1024)

            store.update(job_id, status="running", stage="voice", progress=STAGE_BOUNDS["voice"][0],
                         dialogues=dialogues, message="✏️ ပြင်ဆင်ထားသော Timeline ဖြင့် အသံ ပြန်သွင်းနေပါသည်...")
            voice_cfg = _voice_config(payload.get("lang", "my"), payload.get("voice", "thiha"))
            mix = tts_engine.build_narration(
                dialogues=dialogues, voice_cfg=voice_cfg, duration=duration,
                work_dir=work_dir, tag=f"{job_id}_v2",
                progress=self._stage(job_id, "voice"), cancel=self._cancel(job_id),
            )
            store.update(job_id, stage="mix")
            narration_mp3 = work_dir / f"narration_{job_id}_v2.mp3"
            master_audio(mix.audio_path, narration_mp3, duration,
                         loudnorm=config.settings.loudness_normalize,
                         bitrate=config.settings.audio_bitrate)

            ass_path = None
            srt_path = None
            target_w, target_h = self._target_size(payload, info)
            if payload.get("enable_subtitles", True):
                store.update(job_id, stage="subtitles")
                ass_path = str(work_dir / f"{job_id}_v2.ass")
                build_ass(
                    dialogues=dialogues, duration=duration, ass_path=ass_path,
                    hook_line1=payload.get("hook_line1", job.hook_line1),
                    hook_line2=payload.get("hook_line2", job.hook_line2),
                    font_size=int(payload.get("sub_font_size", 42)),
                    v_margin=int(target_h * (float(payload.get("sub_v_pos_percent", 22)) / 100.0)),
                    hex_color=payload.get("sub_color_hex", "#00F2FE"),
                    bg_style=payload.get("sub_bg_style", "Solid Box"),
                    play_res=(target_w, target_h),
                    hook_seconds=float(payload.get("hook_seconds", 0)),
                    uppercase_hook=bool(payload.get("hook_uppercase", False)),
                )
                srt_path = str(work_dir / f"{job_id}_v2.srt")
                export_srt(dialogues, srt_path)

            store.update(job_id, stage="render", message="🎬 ဗီဒီယို ပြန်လည် ထုတ်လုပ်နေပါသည်...")
            output_name = f"recap_{job_id}_v{int(time.time())}.mp4"
            output_path = str(config.OUTPUT_DIR / output_name)
            logo_path = payload.get("logo_path", job.request.get("logo_path"))
            logo_pos = None
            if logo_path and payload.get("logo_pos_x") is not None and payload.get("logo_pos_y") is not None:
                logo_pos = (float(payload["logo_pos_x"]), float(payload["logo_pos_y"]))
            render_master(
                input_video=input_video, narration_wav=str(narration_mp3),
                output_video=output_path, ass_path=ass_path,
                logo_path=str(config.resolve(logo_path)) if logo_path else None,
                logo_pos=logo_pos,
                reframe=payload.get("reframe_mode", job.request.get("reframe_mode", "Smart Blur Background")),
                mute_original=bool(payload.get("mute_original", True)),
                keep_original_level=float(payload.get("original_level", 0.12)),
                narration_gain=float(payload.get("narration_gain", 1.3)),
                quality=payload.get("quality", job.request.get("quality", "balanced")),
                target_size=(target_w, target_h), duration=duration,
                progress=self._stage(job_id, "render"), cancel=self._cancel(job_id),
            )
            published = self._publish_extras(job_id, output_path, ass_path, srt_path, narration_mp3)
            stats = {**(job.stats or {}), "voice": mix.stats(),
                     "output": {"size": os.path.getsize(output_path)}}
            store.update(job_id, status="completed", progress=100, stage="finalize",
                         output_video=config.rel(output_path),
                         download_url=f"/api/download/{output_name}",
                         preview_url=f"/api/asset?path={config.rel(output_path)}",
                         stats=stats, **published,
                         message="✨ ပြင်ဆင်ချက်များဖြင့် ပြန်ထုတ်ပြီးပါပြီ!")
            safe_rmtree(work_dir)
        except JobCancelled:
            store.update(job_id, status="cancelled", message="⏹️ ရပ်တန့်လိုက်ပါပြီ")
        except Exception as exc:  # noqa: BLE001
            log.exception("rerender %s failed", job_id)
            store.update(job_id, status="failed", error=str(exc)[:900],
                         message=f"❌ {str(exc)[:800]}")

    # ── assets published next to the master ────────────────────────────
    def _publish_extras(self, job_id: str, output_path: str, ass_path: Optional[str],
                        srt_path: Optional[str], narration_mp3: str) -> dict[str, Any]:
        extras: dict[str, Any] = {}
        base = Path(output_path).stem
        try:
            if srt_path and Path(srt_path).exists():
                target = config.OUTPUT_DIR / f"{base}.srt"
                shutil.copyfile(srt_path, target)
                extras["srt_url"] = f"/api/download/{target.name}"
            if ass_path and Path(ass_path).exists():
                target = config.OUTPUT_DIR / f"{base}.ass"
                shutil.copyfile(ass_path, target)
                extras["ass_url"] = f"/api/download/{target.name}"
        except Exception as exc:
            log.warning("publishing subtitle files failed: %s", exc)
        try:
            if narration_mp3 and Path(narration_mp3).exists():
                target = config.OUTPUT_DIR / f"{base}_narration.mp3"
                shutil.copyfile(narration_mp3, target)
                extras["audio_url"] = f"/api/download/{target.name}"
        except Exception as exc:
            log.warning("publishing narration mp3 failed: %s", exc)
        return extras

    @staticmethod
    def _target_size(payload: dict[str, Any], info: dict[str, Any]) -> tuple[int, int]:
        aspect = payload.get("output_aspect", "9:16")
        if aspect == "original":
            w = info.get("width") or 1280
            h = info.get("height") or 720
            # keep even dimensions and cap at 1920 for sane encode times
            scale = min(1.0, 1920 / max(w, h, 1))
            return max(2, int(w * scale) // 2 * 2), max(2, int(h * scale) // 2 * 2)
        if aspect == "1:1":
            return 1080, 1080
        if aspect == "16:9":
            return 1280, 720
        return 720, 1280

    # ── thumbnail ──────────────────────────────────────────────────────
    def generate_thumbnail(self, video_path: str, timestamp: float, hook1: str, hook2: str,
                           output_path: str, style: str = "bold") -> dict:
        from PIL import Image, ImageDraw
        from .fonts import get_mm_pil_font

        width, height = 720, 1280
        frame_path = config.TMP_DIR / f"frame_{uuid.uuid4().hex[:8]}.png"
        run_ffmpeg([
            "-y", "-ss", f"{max(0.0, timestamp):.3f}", "-i", video_path, "-frames:v", "1",
            "-vf", f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height}",
            str(frame_path),
        ], check=True)
        if not frame_path.exists():
            raise RuntimeError("Frame ဖမ်းယူ၍ မရပါ - စက္ကန့် အနေအထားကို ပြောင်းကြည့်ပါ။")

        base = Image.open(frame_path).convert("RGBA")
        shade = Image.new("RGBA", base.size, (0, 0, 0, 0))
        draw_shade = ImageDraw.Draw(shade)
        draw_shade.rectangle([0, 0, width, int(height * 0.26)], fill=(0, 0, 0, 190))
        draw_shade.rectangle([0, int(height * 0.72), width, height], fill=(0, 0, 0, 150))
        base = Image.alpha_composite(base, shade)

        draw = ImageDraw.Draw(base)
        font_big = get_mm_pil_font(int(width * 0.072), bold=True)
        font_small = get_mm_pil_font(int(width * 0.048), bold=True)
        accent = (0, 242, 254, 255)
        yellow = (255, 214, 10, 255)

        def wrap(text: str, font, max_width: int) -> list[str]:
            words = (text or "").split()
            if not words:
                return []
            lines, current = [], words[0]
            for word in words[1:]:
                probe = f"{current} {word}"
                if draw.textlength(probe, font=font) <= max_width:
                    current = probe
                else:
                    lines.append(current)
                    current = word
            lines.append(current)
            return lines[:3]

        top_lines = wrap(hook1, font_big, int(width * 0.9))
        bottom_lines = wrap(hook2, font_small, int(width * 0.86))
        y = int(height * 0.055)
        for line in top_lines:
            draw.text((width // 2, y), line, font=font_big, fill=yellow, anchor="ma",
                      stroke_width=7, stroke_fill=(0, 0, 0, 255))
            y += int(width * 0.088)
        y = int(height * 0.755)
        for line in bottom_lines:
            draw.text((width // 2, y), line, font=font_small, fill=accent, anchor="ma",
                      stroke_width=5, stroke_fill=(0, 0, 0, 255))
            y += int(width * 0.062)

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        base.convert("RGB").save(output_path, "JPEG", quality=94, optimize=True)
        frame_path.unlink(missing_ok=True)
        return {"path": output_path, "size": os.path.getsize(output_path)}

    # ── shorts splitter ────────────────────────────────────────────────
    def split_video(self, video_path: str, slice_sec: int, aspect: str,
                    progress: Optional[callable] = None) -> list[dict]:
        info = get_video_info(video_path)
        duration = info["duration"]
        if duration <= 0:
            raise ValueError("ဗီဒီယို ဖိုင် မမှန်ကန်ပါ")
        slice_sec = max(5, int(slice_sec))
        total = max(1, math.ceil(duration / slice_sec))
        tag = uuid.uuid4().hex[:6]
        # Part files live in the output folder so they can be downloaded
        # immediately and are cleaned up by the janitor.
        jobs: list[tuple[int, float, float]] = []
        for index in range(total):
            start = index * slice_sec
            length = min(slice_sec, duration - start)
            if length <= 0.2:
                continue
            jobs.append((index, start, length))

        results: dict[int, dict] = {}
        workers = max(1, min(4, (os.cpu_count() or 2)))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(self._split_one, video_path, index, start, length,
                            aspect, info, tag): index
                for index, start, length in jobs
            }
            done = 0
            for future in as_completed(futures):
                index = futures[future]
                done += 1
                try:
                    part = future.result()
                    if part:
                        results[index] = part
                except Exception as exc:
                    log.warning("split part %s failed: %s", index, exc)
                if progress:
                    progress(done / max(1, len(jobs)) * 100,
                             f"✂️ အပိုင်း {done}/{len(jobs)} ခွဲထုတ်ပြီးပါပြီ")
        return [results[key] for key in sorted(results)]

    def _split_one(self, video_path: str, index: int, start: float, length: float,
                   aspect: str, info: dict, tag: str) -> Optional[dict]:
        name = f"part_{index + 1:02d}_{tag}.mp4"
        out_path = config.OUTPUT_DIR / name
        same_aspect = False
        if aspect == "original":
            same_aspect = True
        elif aspect == "9:16" and info["height"] > info["width"]:
            same_aspect = True
        elif aspect == "16:9" and info["width"] >= info["height"]:
            same_aspect = True

        if same_aspect and not config.settings.force_reencode:
            # stream copy: near instant, no quality loss
            run_ffmpeg([
                "-y", "-ss", f"{start:.3f}", "-i", video_path, "-t", f"{length:.3f}",
                "-c", "copy", "-avoid_negative_ts", "make_zero", "-movflags", "+faststart",
                str(out_path),
            ], check=False)
        if not out_path.exists() or out_path.stat().st_size < 2048:
            if aspect == "9:16":
                vf = "scale=720:1280:force_original_aspect_ratio=increase,crop=720:1280"
            elif aspect == "1:1":
                vf = "scale=1080:1080:force_original_aspect_ratio=increase,crop=1080:1080"
            elif aspect == "16:9":
                vf = "scale=1280:720:force_original_aspect_ratio=decrease,pad=1280:720:(ow-iw)/2:(oh-ih)/2"
            else:
                vf = "null"
            run_ffmpeg([
                "-y", "-ss", f"{start:.3f}", "-i", video_path, "-t", f"{length:.3f}",
                "-vf", vf, "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
                "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k",
                "-movflags", "+faststart", str(out_path),
            ], check=True)
        if not out_path.exists() or out_path.stat().st_size < 2048:
            return None
        return {
            "part": index + 1,
            "filename": name,
            "url": f"/api/download/{name}",
            "preview_url": f"/api/asset?path={config.rel(out_path)}",
            "duration": round(get_media_duration(out_path), 2),
            "size": out_path.stat().st_size,
        }
