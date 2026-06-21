#!/usr/bin/env python3
"""Extract public Bilibili metadata, audio, transcripts, and comments."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path


BASE = "https://api.bilibili.com"
TZ = timezone(timedelta(hours=8))
MIXIN_KEY_ENC_TAB = [
    46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35,
    27, 43, 5, 49, 33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13,
    37, 48, 7, 16, 24, 55, 40, 61, 26, 17, 0, 1, 60, 51, 30, 4,
    22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11, 36, 20, 34, 44, 52,
]


def headers(bvid: str | None = None) -> dict[str, str]:
    referer = "https://www.bilibili.com/"
    if bvid:
        referer = f"https://www.bilibili.com/video/{bvid}/"
    return {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"
        ),
        "Referer": referer,
        "Accept": "application/json,text/plain,*/*",
    }


def request_json(url: str, bvid: str | None = None) -> dict:
    req = urllib.request.Request(url, headers=headers(bvid))
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def api_get(path: str, params: dict, bvid: str | None = None, signed: bool = False, mixin_key: str | None = None) -> dict:
    if signed:
        if not mixin_key:
            raise ValueError("signed=True requires mixin_key")
        params = sign_params(params, mixin_key)
    url = BASE + path + "?" + urllib.parse.urlencode(params)
    obj = request_json(url, bvid)
    if obj.get("code") != 0:
        raise RuntimeError(f"API error {obj.get('code')}: {obj.get('message')} url={url}")
    return obj


def extract_bvid(source: str) -> str:
    match = re.search(r"(BV[0-9A-Za-z]+)", source)
    if not match:
        raise ValueError(f"Could not find BVID in: {source}")
    return match.group(1)


def fmt_ts(sec: int | None) -> str:
    if not sec:
        return ""
    return datetime.fromtimestamp(int(sec), TZ).strftime("%Y-%m-%d %H:%M:%S")


def fmt_duration(seconds: int | None) -> str:
    if not seconds:
        return "0:00"
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def srt_ts(seconds: float | int | None) -> str:
    total_ms = max(0, int(round(float(seconds or 0) * 1000)))
    ms = total_ms % 1000
    total_s = total_ms // 1000
    s = total_s % 60
    total_m = total_s // 60
    m = total_m % 60
    h = total_m // 60
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def safe_slug(value: str, default: str = "subtitle") -> str:
    cleaned = re.sub(r"[^0-9A-Za-z._-]+", "_", value.strip())
    cleaned = cleaned.strip("._-")
    return cleaned or default


def normalize_media_url(url: str) -> str:
    if url.startswith("//"):
        return "https:" + url
    return url


def write_bilibili_subtitle_outputs(payload: dict, out_dir: Path, stem: str, lang: str) -> dict:
    body = payload.get("body") or []
    json_path = out_dir / f"{stem}_{safe_slug(lang)}.subtitle.json"
    txt_path = out_dir / f"{stem}_{safe_slug(lang)}.txt"
    srt_path = out_dir / f"{stem}_{safe_slug(lang)}.srt"

    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    txt_lines = [(item.get("content") or "").strip() for item in body]
    txt_path.write_text("\n".join(line for line in txt_lines if line).rstrip() + "\n", encoding="utf-8")

    srt_lines = []
    for i, item in enumerate(body, 1):
        content = (item.get("content") or "").strip()
        if not content:
            continue
        srt_lines.extend(
            [
                str(i),
                f"{srt_ts(item.get('from'))} --> {srt_ts(item.get('to'))}",
                content,
                "",
            ]
        )
    srt_path.write_text("\n".join(srt_lines).rstrip() + "\n", encoding="utf-8")
    return {"json": str(json_path), "txt": str(txt_path), "srt": str(srt_path)}


def resolve_asr_backend(requested: str) -> str:
    aliases = {
        "whisper": "openai-whisper",
        "openai": "openai-whisper",
        "openai-whisper": "openai-whisper",
        "faster": "faster-whisper",
        "faster-whisper": "faster-whisper",
        "funasr": "funasr",
        "sensevoice": "funasr",
        "auto": "auto",
    }
    key = aliases.get((requested or "auto").lower())
    if not key:
        raise ValueError(f"Unsupported ASR backend: {requested}")
    if key != "auto":
        return key
    for module_name, backend in (
        ("faster_whisper", "faster-whisper"),
        ("funasr", "funasr"),
        ("whisper", "openai-whisper"),
    ):
        if importlib.util.find_spec(module_name):
            return backend
    return "openai-whisper"


def asr_default_model(backend: str, asr_model: str | None, whisper_model: str | None) -> str:
    if asr_model:
        return asr_model
    if backend == "funasr":
        return "iic/SenseVoiceSmall"
    return whisper_model or "base"


def detect_device(device: str) -> str:
    if device != "auto":
        return device
    try:
        import torch  # type: ignore

        return "cuda" if torch.cuda.is_available() else "cpu"
    except Exception:
        return "cpu"


def add_site_packages(paths: list[str] | None) -> None:
    for value in paths or []:
        for raw_path in value.split(os.pathsep):
            path = raw_path.strip()
            if path and path not in sys.path:
                sys.path.append(path)


def write_source_md(view: dict, out_dir: Path) -> None:
    data = view["data"]
    lines = [
        f"# {data.get('title', '')}",
        "",
        f"- URL: https://www.bilibili.com/video/{data.get('bvid')}/",
        f"- BVID: {data.get('bvid')}",
        f"- AID: {data.get('aid')}",
        f"- UP: {(data.get('owner') or {}).get('name', '')}",
        f"- Published: {fmt_ts(data.get('pubdate'))} (UTC+8)",
        f"- Duration: {fmt_duration(data.get('duration'))}",
        f"- Parts: {data.get('videos')}",
        "",
        "## Description",
        "",
        data.get("desc") or "",
        "",
        "## Parts",
        "",
    ]
    for page in data.get("pages") or []:
        lines.append(
            f"{page.get('page')}. cid={page.get('cid')} "
            f"duration={fmt_duration(page.get('duration'))} - {page.get('part', '')}"
        )
    (out_dir / "source.md").write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def select_pages(pages: list[dict], parts_arg: str | None) -> list[dict]:
    if not pages:
        return []
    if not parts_arg or parts_arg == "key":
        if len(pages) == 1:
            return pages
        pattern = re.compile(r"(Agentic|Summary|总结|实操|打造|冠军|方案|Challenge|打卡)", re.I)
        selected = [p for p in pages if pattern.search(p.get("part", ""))]
        return selected or [pages[0]]
    if parts_arg == "all":
        return pages
    wanted = {int(x.strip()) for x in parts_arg.split(",") if x.strip()}
    return [p for p in pages if int(p.get("page", 0)) in wanted]


def download_file(url: str, path: Path, bvid: str) -> None:
    req = urllib.request.Request(url, headers=headers(bvid))
    with urllib.request.urlopen(req, timeout=60) as resp, path.open("wb") as fh:
        while True:
            chunk = resp.read(1024 * 1024)
            if not chunk:
                break
            fh.write(chunk)


def download_audio_with_bilibili_api(bvid: str, page: dict, audio_path: Path, force: bool = False) -> Path:
    if audio_path.exists() and not force:
        return audio_path
    cid = str(page["cid"])
    play = api_get(
        "/x/player/playurl",
        {"bvid": bvid, "cid": cid, "qn": 16, "fnval": 16, "fourk": 1},
        bvid,
    )
    audios = (((play.get("data") or {}).get("dash") or {}).get("audio") or [])
    if not audios:
        raise RuntimeError(f"No public audio in playurl for cid={cid}")
    audio = sorted(audios, key=lambda x: x.get("bandwidth", 0), reverse=True)[0]
    url = audio.get("baseUrl") or audio.get("base_url")
    download_file(url, audio_path, bvid)
    return audio_path


def download_audio_with_ytdlp(
    bvid: str,
    page: dict,
    out_dir: Path,
    stem: str,
    cookies_from_browser: str | None = None,
    force: bool = False,
) -> Path:
    executable = shutil.which("yt-dlp") or shutil.which("yt-dlp.exe")
    if importlib.util.find_spec("yt_dlp"):
        base_cmd = [sys.executable, "-m", "yt_dlp"]
    elif executable:
        base_cmd = [executable]
    else:
        raise RuntimeError("yt-dlp is not installed or not on PATH")
    existing = sorted(
        p for p in out_dir.glob(f"{stem}.*")
        if p.suffix.lower() not in {".wav", ".json", ".txt", ".srt"}
    )
    if existing and not force:
        return existing[0]
    template = str(out_dir / f"{stem}.%(ext)s")
    url = f"https://www.bilibili.com/video/{bvid}/"
    if int(page.get("page") or 1) > 1:
        url += f"?p={int(page['page'])}"
    cmd = [
        *base_cmd,
        "--no-playlist",
        "--add-header",
        f"Referer: https://www.bilibili.com/video/{bvid}/",
        "--add-header",
        f"User-Agent: {headers(bvid)['User-Agent']}",
        "-f",
        "ba/bestaudio",
        "-o",
        template,
    ]
    if cookies_from_browser:
        cmd.extend(["--cookies-from-browser", cookies_from_browser])
    cmd.append(url)
    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(
            "yt-dlp failed for Bilibili audio. Bilibili may return HTTP 412 without browser cookies; "
            "retry with --cookies-from-browser chrome/edge or use --audio-source auto."
        ) from exc
    candidates = sorted(
        p for p in out_dir.glob(f"{stem}.*")
        if p.suffix.lower() not in {".wav", ".json", ".txt", ".srt"}
    )
    if not candidates:
        raise RuntimeError(f"yt-dlp did not create an audio file for {bvid} page {page.get('page')}")
    return candidates[0]


def ensure_wav_for_pages(
    bvid: str,
    pages: list[dict],
    out_dir: Path,
    force: bool = False,
    audio_source: str = "auto",
    cookies_from_browser: str | None = None,
) -> list[dict]:
    manifest = []
    for page in pages:
        cid = str(page["cid"])
        stem = f"p{int(page['page']):02d}_{cid}"
        m4s = out_dir / f"{stem}.m4s"
        wav = out_dir / f"{stem}.wav"
        audio_file = m4s
        if force or not audio_file.exists():
            if audio_source == "yt-dlp":
                audio_file = download_audio_with_ytdlp(bvid, page, out_dir, stem, cookies_from_browser, force)
            else:
                try:
                    audio_file = download_audio_with_bilibili_api(bvid, page, m4s, force)
                except Exception:
                    if audio_source != "auto":
                        raise
                    audio_file = download_audio_with_ytdlp(bvid, page, out_dir, stem, cookies_from_browser, force)
        if force or not wav.exists():
            subprocess.run(
                ["ffmpeg", "-hide_banner", "-y", "-i", str(audio_file), "-ar", "16000", "-ac", "1", str(wav)],
                check=True,
            )
        manifest.append(
            {
                "page": page.get("page"),
                "cid": cid,
                "part": page.get("part", ""),
                "duration": page.get("duration"),
                "audio": str(audio_file),
                "wav": str(wav),
            }
        )
    (out_dir / "audio_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def transcribe_wavs_openai_whisper(
    manifest: list[dict],
    out_dir: Path,
    model_name: str,
    language: str,
    force: bool = False,
) -> list[dict]:
    import torch  # type: ignore
    import whisper  # type: ignore

    model = whisper.load_model(model_name, download_root=str(Path.home() / ".cache" / "whisper"))
    results = []
    for item in manifest:
        stem = f"p{int(item['page']):02d}_{item['cid']}"
        txt_path = out_dir / f"{stem}.txt"
        json_path = out_dir / f"{stem}.json"
        if txt_path.exists() and not force:
            results.append({**item, "transcript_txt": str(txt_path), "transcript_json": str(json_path)})
            continue
        result = model.transcribe(
            item["wav"],
            language=language,
            task="transcribe",
            fp16=bool(torch.cuda.is_available()),
            verbose=False,
        )
        result["backend"] = "openai-whisper"
        result["model"] = model_name
        txt_path.write_text(result.get("text", ""), encoding="utf-8")
        json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        results.append({**item, "transcript_txt": str(txt_path), "transcript_json": str(json_path)})
    return results


def transcribe_wavs_faster_whisper(
    manifest: list[dict],
    out_dir: Path,
    model_name: str,
    language: str,
    device: str,
    compute_type: str,
    force: bool = False,
) -> list[dict]:
    from faster_whisper import WhisperModel  # type: ignore

    resolved_device = detect_device(device)
    resolved_compute = compute_type
    if resolved_compute == "auto":
        resolved_compute = "float16" if resolved_device == "cuda" else "int8"
    model = WhisperModel(
        model_name,
        device=resolved_device,
        compute_type=resolved_compute,
        download_root=str(Path.home() / ".cache" / "faster-whisper"),
    )
    results = []
    for item in manifest:
        stem = f"p{int(item['page']):02d}_{item['cid']}"
        txt_path = out_dir / f"{stem}.txt"
        json_path = out_dir / f"{stem}.json"
        if txt_path.exists() and not force:
            results.append({**item, "transcript_txt": str(txt_path), "transcript_json": str(json_path)})
            continue
        segments_iter, info = model.transcribe(item["wav"], language=language, task="transcribe", vad_filter=True)
        segments = []
        for segment in segments_iter:
            segments.append(
                {
                    "id": getattr(segment, "id", None),
                    "start": getattr(segment, "start", None),
                    "end": getattr(segment, "end", None),
                    "text": getattr(segment, "text", ""),
                    "avg_logprob": getattr(segment, "avg_logprob", None),
                    "no_speech_prob": getattr(segment, "no_speech_prob", None),
                }
            )
        text = "".join(segment["text"] for segment in segments).strip()
        result = {
            "backend": "faster-whisper",
            "model": model_name,
            "device": resolved_device,
            "compute_type": resolved_compute,
            "language": getattr(info, "language", language),
            "duration": getattr(info, "duration", None),
            "text": text,
            "segments": segments,
        }
        txt_path.write_text(text, encoding="utf-8")
        json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        results.append({**item, "transcript_txt": str(txt_path), "transcript_json": str(json_path)})
    return results


def funasr_text(result: object) -> str:
    if isinstance(result, list):
        parts = []
        for item in result:
            if isinstance(item, dict):
                parts.append(str(item.get("text") or ""))
        return "\n".join(part for part in parts if part).strip()
    if isinstance(result, dict):
        return str(result.get("text") or "").strip()
    return str(result or "").strip()


def transcribe_wavs_funasr(
    manifest: list[dict],
    out_dir: Path,
    model_name: str,
    language: str,
    device: str,
    force: bool = False,
) -> list[dict]:
    from funasr import AutoModel  # type: ignore

    resolved_device = detect_device(device)
    model = AutoModel(model=model_name, vad_model="fsmn-vad", device=resolved_device)
    results = []
    for item in manifest:
        stem = f"p{int(item['page']):02d}_{item['cid']}"
        txt_path = out_dir / f"{stem}.txt"
        json_path = out_dir / f"{stem}.json"
        if txt_path.exists() and not force:
            results.append({**item, "transcript_txt": str(txt_path), "transcript_json": str(json_path)})
            continue
        raw = model.generate(input=item["wav"], language=language)
        text = funasr_text(raw)
        result = {
            "backend": "funasr",
            "model": model_name,
            "device": resolved_device,
            "language": language,
            "text": text,
            "raw": raw,
        }
        txt_path.write_text(text, encoding="utf-8")
        json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        results.append({**item, "transcript_txt": str(txt_path), "transcript_json": str(json_path)})
    return results


def transcribe_wavs(
    manifest: list[dict],
    out_dir: Path,
    backend: str,
    model_name: str,
    site_packages: list[str] | None,
    force: bool = False,
    device: str = "auto",
    compute_type: str = "auto",
    language: str = "zh",
) -> list[dict]:
    add_site_packages(site_packages)
    resolved_backend = resolve_asr_backend(backend)
    if resolved_backend == "faster-whisper":
        return transcribe_wavs_faster_whisper(manifest, out_dir, model_name, language, device, compute_type, force)
    if resolved_backend == "funasr":
        return transcribe_wavs_funasr(manifest, out_dir, model_name, language, device, force)
    return transcribe_wavs_openai_whisper(manifest, out_dir, model_name, language, force)


def get_mixin_key(bvid: str) -> str:
    obj = request_json(BASE + "/x/web-interface/nav", bvid)
    wbi = ((obj.get("data") or {}).get("wbi_img") or {})
    img_key = Path(urllib.parse.urlparse(wbi.get("img_url", "")).path).stem
    sub_key = Path(urllib.parse.urlparse(wbi.get("sub_url", "")).path).stem
    key = img_key + sub_key
    return "".join(key[i] for i in MIXIN_KEY_ENC_TAB)[:32]


def sign_params(params: dict, mixin_key: str) -> dict:
    signed = dict(params)
    signed["wts"] = int(time.time())
    cleaned = {
        key: "".join(ch for ch in str(value) if ch not in "!'()*")
        for key, value in signed.items()
    }
    query = urllib.parse.urlencode(sorted(cleaned.items()))
    signed["w_rid"] = hashlib.md5((query + mixin_key).encode()).hexdigest()
    return signed


def reply_id(reply: dict) -> str:
    return str(reply.get("rpid_str") or reply.get("rpid") or "")


def reply_text(reply: dict) -> str:
    content = reply.get("content") or {}
    return (content.get("message") or "").replace("\r\n", "\n").replace("\r", "\n")


def member_name(reply: dict) -> str:
    return ((reply.get("member") or {}).get("uname") or "").strip()


def compact_reply(reply: dict) -> dict:
    content = reply.get("content") or {}
    pics = []
    for pic in content.get("pictures") or []:
        url = pic.get("img_src") or pic.get("m_img_src") or pic.get("src") or pic.get("url")
        if url:
            pics.append(url)
    links = []
    jump = content.get("jump_url") or {}
    if isinstance(jump, dict):
        for title, value in jump.items():
            if isinstance(value, dict):
                url = value.get("pc_url") or value.get("app_url_schema") or ""
                if url.startswith("//"):
                    url = "https:" + url
                if url:
                    links.append({"title": title, "url": url})
    return {
        "rpid": reply_id(reply),
        "root": str(reply.get("root_str") or reply.get("root") or ""),
        "parent": str(reply.get("parent_str") or reply.get("parent") or ""),
        "uname": member_name(reply),
        "mid": str(((reply.get("member") or {}).get("mid") or reply.get("mid_str") or reply.get("mid") or "")),
        "time": fmt_ts(reply.get("ctime")),
        "ctime": int(reply.get("ctime") or 0),
        "like": int(reply.get("like") or 0),
        "message": reply_text(reply),
        "pictures": pics,
        "links": links,
        "rcount": int(reply.get("rcount") or reply.get("count") or 0),
        "up_liked": bool((reply.get("up_action") or {}).get("like")),
        "up_replied": bool((reply.get("up_action") or {}).get("reply")),
        "parent_reply_member": reply.get("parent_reply_member") or None,
    }


def fetch_child_replies(aid: str, bvid: str, root_rpid: str, expected: int = 0) -> tuple[list[dict], int | None]:
    children = []
    seen = set()
    pn = 1
    total = None
    while True:
        obj = api_get("/x/v2/reply/reply", {"type": 1, "oid": aid, "root": root_rpid, "pn": pn, "ps": 20}, bvid)
        data = obj.get("data") or {}
        total = total if total is not None else ((data.get("page") or {}).get("count"))
        replies = data.get("replies") or []
        if not replies:
            break
        for reply in replies:
            rid = reply_id(reply)
            if rid and rid not in seen:
                seen.add(rid)
                children.append(reply)
        if total and len(children) >= int(total):
            break
        if expected and len(children) >= expected and (not total or expected >= int(total)):
            break
        pn += 1
        time.sleep(0.2)
    return children, total


def quote_block(text: str) -> str:
    if not text:
        return "> "
    return "\n".join("> " + line for line in text.split("\n"))


def fetch_comments(aid: str, bvid: str, out_dir: Path, mode: int = 3) -> dict:
    mixin_key = get_mixin_key(bvid)
    roots = []
    seen = set()
    next_value = 0
    all_count = None
    for _ in range(40):
        obj = api_get(
            "/x/v2/reply/wbi/main",
            {"type": 1, "oid": aid, "mode": mode, "next": next_value, "ps": 20, "web_location": 1315875},
            bvid,
            signed=True,
            mixin_key=mixin_key,
        )
        data = obj.get("data") or {}
        cursor = data.get("cursor") or {}
        all_count = cursor.get("all_count", all_count)
        candidates = []
        candidates.extend(data.get("top_replies") or [])
        candidates.extend(data.get("replies") or [])
        top = data.get("top") or {}
        if isinstance(top, dict):
            for key in ("admin", "upper"):
                value = top.get(key)
                if isinstance(value, dict) and value.get("rpid"):
                    candidates.append(value)
        for reply in candidates:
            rid = reply_id(reply)
            if rid and rid not in seen:
                seen.add(rid)
                roots.append(reply)
        if cursor.get("is_end"):
            break
        new_next = cursor.get("next")
        if new_next is None or new_next == next_value:
            break
        next_value = new_next
        time.sleep(0.25)

    items = []
    for reply in roots:
        item = compact_reply(reply)
        raw_children = []
        if item["rcount"] > 0:
            try:
                raw_children, _ = fetch_child_replies(aid, bvid, item["rpid"], item["rcount"])
            except Exception as exc:
                item["child_fetch_error"] = str(exc)
                raw_children = reply.get("replies") or []
        item["children"] = [compact_reply(child) for child in raw_children]
        items.append(item)

    root_ids = {item["rpid"] for item in items}
    for item in items:
        item["children"] = [child for child in item["children"] if child["rpid"] not in root_ids]

    fetched_at = datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S")
    result = {
        "source": f"https://www.bilibili.com/video/{bvid}/",
        "aid": aid,
        "bvid": bvid,
        "fetched_at": fetched_at,
        "wbi_main_all_count": all_count,
        "top_level_count": len(items),
        "child_reply_count": sum(len(item["children"]) for item in items),
        "items": items,
    }
    result["total_fetched_comments"] = result["top_level_count"] + result["child_reply_count"]
    (out_dir / "comments_raw.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    write_comments_md(result, out_dir / "comments.md")
    return result


def write_comments_md(raw: dict, path: Path) -> None:
    lines = [
        "# Comments",
        "",
        f"- Source: {raw['source']}",
        f"- Fetched: {raw['fetched_at']} (UTC+8)",
        f"- WBI all_count: {raw.get('wbi_main_all_count')}",
        f"- Fetched: top-level {raw['top_level_count']}, child replies {raw['child_reply_count']}, total {raw['total_fetched_comments']}",
        "",
    ]
    for i, item in enumerate(raw["items"], 1):
        lines.append(f"## Comment {i}: {item['uname']}")
        meta = [
            f"rpid: {item['rpid']}",
            f"mid: {item['mid']}",
            f"time: {item['time']}",
            f"likes: {item['like']}",
            f"children: {len(item['children'])}",
        ]
        lines.append("- " + "; ".join(meta))
        lines.append("")
        lines.append(quote_block(item["message"]))
        if item.get("links"):
            lines.append("")
            lines.append("Links:")
            for link in item["links"]:
                lines.append(f"- {link['title']}: {link['url']}")
        if item.get("pictures"):
            lines.append("")
            lines.append("Pictures:")
            for url in item["pictures"]:
                lines.append(f"- {url}")
        lines.append("")
        if item["children"]:
            lines.append("### Child replies")
            lines.append("")
            for j, child in enumerate(item["children"], 1):
                parent = child.get("parent_reply_member") or {}
                parent_note = f"; parent: {parent.get('name')}" if parent.get("name") else ""
                lines.append(
                    f"{j}. **{child['uname']}** "
                    f"(rpid: {child['rpid']}; time: {child['time']}; likes: {child['like']}{parent_note})"
                )
                lines.append("")
                lines.append(quote_block(child["message"]))
                lines.append("")
        lines.append("")
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def check_subtitles(bvid: str, pages: list[dict]) -> list[dict]:
    result = []
    for page in pages:
        obj = api_get("/x/player/v2", {"bvid": bvid, "cid": page["cid"]}, bvid)
        data = obj.get("data") or {}
        result.append(
            {
                "page": page.get("page"),
                "cid": page.get("cid"),
                "part": page.get("part"),
                "need_login_subtitle": data.get("need_login_subtitle"),
                "subtitles": (data.get("subtitle") or {}).get("subtitles") or [],
            }
        )
    return result


def fetch_subtitle_payload(url: str, bvid: str) -> dict:
    req = urllib.request.Request(normalize_media_url(url), headers=headers(bvid))
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def download_available_subtitles(subtitles: list[dict], out_dir: Path, bvid: str, force: bool = False) -> list[dict]:
    outputs = []
    for page_info in subtitles:
        page = int(page_info.get("page") or 1)
        cid = page_info.get("cid")
        stem = f"p{page:02d}_{cid}"
        for sub in page_info.get("subtitles") or []:
            url = sub.get("subtitle_url") or ""
            if not url:
                continue
            lang = sub.get("lan") or sub.get("lan_doc") or sub.get("id_str") or "subtitle"
            expected_txt = out_dir / f"{stem}_{safe_slug(lang)}.txt"
            if expected_txt.exists() and not force:
                files = {
                    "json": str(out_dir / f"{stem}_{safe_slug(lang)}.subtitle.json"),
                    "txt": str(expected_txt),
                    "srt": str(out_dir / f"{stem}_{safe_slug(lang)}.srt"),
                }
            else:
                payload = fetch_subtitle_payload(url, bvid)
                files = write_bilibili_subtitle_outputs(payload, out_dir, stem, lang)
            outputs.append(
                {
                    "page": page,
                    "cid": cid,
                    "lan": sub.get("lan"),
                    "lan_doc": sub.get("lan_doc"),
                    "subtitle_url": normalize_media_url(url),
                    **files,
                }
            )
    (out_dir / "subtitle_manifest.json").write_text(json.dumps(outputs, ensure_ascii=False, indent=2), encoding="utf-8")
    return outputs


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", help="Bilibili URL or BVID")
    parser.add_argument("--out", required=True, help="Output directory")
    parser.add_argument("--parts", default="key", help="'key', 'all', or comma-separated page numbers such as 2,20,22")
    parser.add_argument("--download-audio", action="store_true", help="Download selected part audio and convert to WAV")
    parser.add_argument("--download-subtitles", action="store_true", help="Download Bilibili subtitle tracks when available")
    parser.add_argument("--audio-source", choices=["auto", "bilibili-api", "yt-dlp"], default="auto", help="Audio downloader to use")
    parser.add_argument("--cookies-from-browser", help="Browser name for yt-dlp cookies, e.g. chrome or edge")
    parser.add_argument("--transcribe", action="store_true", help="Run local ASR on selected WAV files")
    parser.add_argument("--asr-backend", default="auto", help="'auto', 'faster-whisper', 'funasr', or 'openai-whisper'")
    parser.add_argument("--asr-model", help="ASR model name; defaults depend on backend")
    parser.add_argument("--asr-device", default="auto", help="'auto', 'cpu', 'cuda', or backend-specific device")
    parser.add_argument("--asr-compute-type", default="auto", help="faster-whisper compute type, e.g. float16, int8")
    parser.add_argument("--asr-language", default="zh", help="ASR language code")
    parser.add_argument("--asr-site-packages", action="append", default=[], help="Extra site-packages path for ASR imports; can repeat")
    parser.add_argument("--whisper-model", help="Legacy OpenAI Whisper model name")
    parser.add_argument("--whisper-site-packages", help="Legacy extra site-packages path for importing whisper")
    parser.add_argument("--comments", action="store_true", help="Fetch WBI comments and child replies")
    parser.add_argument("--force", action="store_true", help="Re-download/re-run existing outputs")
    args = parser.parse_args()

    bvid = extract_bvid(args.source)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    view = api_get("/x/web-interface/view", {"bvid": bvid}, bvid)
    data = view["data"]
    (out_dir / "metadata.json").write_text(json.dumps(view, ensure_ascii=False, indent=2), encoding="utf-8")
    write_source_md(view, out_dir)

    pages = data.get("pages") or []
    selected = select_pages(pages, args.parts)
    subtitles = check_subtitles(bvid, selected)
    (out_dir / "subtitle_probe.json").write_text(json.dumps(subtitles, ensure_ascii=False, indent=2), encoding="utf-8")

    subtitle_outputs = []
    if args.download_subtitles:
        subtitle_outputs = download_available_subtitles(subtitles, out_dir, bvid, args.force)

    manifest = []
    transcript_results = []
    if args.download_audio or args.transcribe:
        manifest = ensure_wav_for_pages(
            bvid,
            selected,
            out_dir,
            args.force,
            args.audio_source,
            args.cookies_from_browser,
        )
    if args.transcribe:
        site_packages = list(args.asr_site_packages or [])
        if args.whisper_site_packages:
            site_packages.append(args.whisper_site_packages)
        add_site_packages(site_packages)
        backend = resolve_asr_backend(args.asr_backend)
        model_name = asr_default_model(backend, args.asr_model, args.whisper_model)
        transcript_results = transcribe_wavs(
            manifest,
            out_dir,
            backend,
            model_name,
            site_packages,
            args.force,
            args.asr_device,
            args.asr_compute_type,
            args.asr_language,
        )

    comments = None
    if args.comments:
        comments = fetch_comments(str(data["aid"]), bvid, out_dir)

    summary = {
        "bvid": bvid,
        "aid": data.get("aid"),
        "title": data.get("title"),
        "owner": (data.get("owner") or {}).get("name"),
        "published": fmt_ts(data.get("pubdate")),
        "parts_total": len(pages),
        "parts_selected": [{"page": p.get("page"), "cid": p.get("cid"), "part": p.get("part")} for p in selected],
        "metadata": str(out_dir / "metadata.json"),
        "source_md": str(out_dir / "source.md"),
        "subtitle_probe": str(out_dir / "subtitle_probe.json"),
        "subtitle_manifest": str(out_dir / "subtitle_manifest.json") if subtitle_outputs else None,
        "subtitles": subtitle_outputs,
        "audio_manifest": str(out_dir / "audio_manifest.json") if manifest else None,
        "transcripts": transcript_results,
        "comments": str(out_dir / "comments.md") if comments else None,
    }
    (out_dir / "run_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
