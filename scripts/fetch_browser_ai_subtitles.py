"""Fetch Bilibili AI subtitles through an already-open logged-in browser page.

This helper uses the web-access CDP proxy. It does not read browser cookies.
Instead, it asks the Bilibili page to call the same player API it uses:

    https://api.bilibili.com/x/player/wbi/v2

That endpoint can return AI subtitle URLs when the plain /x/player/v2 response
only exposes ai-zh metadata with an empty subtitle_url.
"""

from __future__ import annotations

import argparse
import json
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path


def cdp_eval(cdp_base: str, target: str, js: str, timeout: int = 45) -> dict:
    url = f"{cdp_base.rstrip('/')}/eval?target={urllib.parse.quote(target)}"
    req = urllib.request.Request(
        url,
        data=js.encode("utf-8"),
        method="POST",
        headers={"Content-Type": "text/plain; charset=utf-8"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def safe_slug(value: str) -> str:
    value = re.sub(r"[^\w\u4e00-\u9fff.-]+", "_", value, flags=re.UNICODE).strip("_")
    return value[:80] or "subtitle"


def srt_timestamp(seconds: float) -> str:
    millis = int(round(seconds * 1000))
    hh, rem = divmod(millis, 3_600_000)
    mm, rem = divmod(rem, 60_000)
    ss, ms = divmod(rem, 1000)
    return f"{hh:02}:{mm:02}:{ss:02},{ms:03}"


def fetch_json(url: str, referer: str) -> dict:
    if url.startswith("//"):
        url = "https:" + url
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Referer": referer,
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def page_count(cdp_base: str, target: str) -> int:
    js = """
(() => {
  const state = window.__INITIAL_STATE__ || {};
  const pages = state.videoData?.pages || state.pages || [];
  return { count: pages.length, title: document.title, url: location.href };
})()
""".strip()
    payload = cdp_eval(cdp_base, target, js)
    value = payload.get("value") or {}
    if not value.get("count"):
        raise RuntimeError(f"No Bilibili pages found in target. Page info: {value}")
    return int(value["count"])


def fetch_url_batch(cdp_base: str, target: str, start: int, end: int, sleep_ms: int) -> dict:
    js = f"""
(async () => {{
  const state = window.__INITIAL_STATE__ || {{}};
  const aid = state.aid || state.arc?.aid || state.videoData?.aid;
  const bvid = state.bvid || state.videoData?.bvid;
  const referer = location.href;
  const pages = (state.videoData?.pages || state.pages || []).slice({start}, {end});
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const results = [];
  for (const p of pages) {{
    const ep = `https://api.bilibili.com/x/player/wbi/v2?bvid=${{encodeURIComponent(bvid)}}&cid=${{encodeURIComponent(p.cid)}}&aid=${{encodeURIComponent(aid)}}`;
    try {{
      const r = await fetch(ep, {{credentials: 'include'}});
      const j = await r.json();
      const subs = j?.data?.subtitle?.subtitles || [];
      results.push({{
        page: p.page,
        cid: p.cid,
        part: p.part,
        duration: p.duration,
        code: j.code,
        message: j.message,
        subtitles: subs.map(s => ({{
          lan: s.lan,
          lan_doc: s.lan_doc,
          ai_status: s.ai_status,
          type: s.type,
          id_str: s.id_str,
          subtitle_url: s.subtitle_url || '',
          subtitle_url_v2: s.subtitle_url_v2 || ''
        }}))
      }});
    }} catch (e) {{
      results.push({{
        page: p.page,
        cid: p.cid,
        part: p.part,
        duration: p.duration,
        error: String(e)
      }});
    }}
    await sleep({sleep_ms});
  }}
  return {{ aid, bvid, referer, start: {start}, end: {end}, results }};
}})()
""".strip()
    return cdp_eval(cdp_base, target, js, timeout=60)["value"]


def write_subtitle_outputs(payload: dict, out_dir: Path, stem: str) -> dict:
    body = payload.get("body") or []
    json_path = out_dir / f"{stem}.subtitle.json"
    txt_path = out_dir / f"{stem}.txt"
    srt_path = out_dir / f"{stem}.srt"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [str(item.get("content", "")).strip() for item in body if str(item.get("content", "")).strip()]
    txt_path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    blocks = []
    for idx, item in enumerate(body, 1):
        content = str(item.get("content", "")).strip()
        if not content:
            continue
        start = float(item.get("from", 0))
        end_time = float(item.get("to", start + 1))
        blocks.append(f"{idx}\n{srt_timestamp(start)} --> {srt_timestamp(end_time)}\n{content}\n")
    srt_path.write_text("\n".join(blocks), encoding="utf-8")
    return {
        "json": str(json_path),
        "txt": str(txt_path),
        "srt": str(srt_path),
        "line_count": len(lines),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch Bilibili AI subtitles from a logged-in browser target")
    parser.add_argument("--target", required=True, help="CDP target id of an open Bilibili video tab")
    parser.add_argument("--out", required=True, help="Output directory")
    parser.add_argument("--cdp-base", default="http://localhost:3456", help="web-access CDP proxy base URL")
    parser.add_argument("--batch-size", type=int, default=6)
    parser.add_argument("--sleep-ms", type=int, default=150)
    parser.add_argument("--limit", type=int, default=0, help="Optional max parts to fetch, 0 means all")
    args = parser.parse_args()

    out_root = Path(args.out)
    subtitle_dir = out_root / "browser_ai_subtitles"
    subtitle_dir.mkdir(parents=True, exist_ok=True)

    count = page_count(args.cdp_base, args.target)
    if args.limit > 0:
        count = min(count, args.limit)

    all_results = []
    meta = {}
    for start in range(0, count, args.batch_size):
        end = min(start + args.batch_size, count)
        batch = fetch_url_batch(args.cdp_base, args.target, start, end, args.sleep_ms)
        meta = {k: batch.get(k) for k in ("aid", "bvid", "referer")}
        all_results.extend(batch["results"])
        with_url = sum(
            1 for item in all_results if any(s.get("subtitle_url") for s in item.get("subtitles", []))
        )
        print(f"batch {start + 1}-{end}: collected={len(all_results)} with_url={with_url}", flush=True)
        time.sleep(0.35)

    url_manifest = {
        **meta,
        "count": len(all_results),
        "with_url": sum(1 for item in all_results if any(s.get("subtitle_url") for s in item.get("subtitles", []))),
        "results": all_results,
    }
    (out_root / "browser_ai_subtitle_urls.json").write_text(
        json.dumps(url_manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    outputs = []
    for item in all_results:
        selected = next((s for s in item.get("subtitles", []) if s.get("subtitle_url")), None)
        record = {
            "page": item.get("page"),
            "cid": item.get("cid"),
            "part": item.get("part"),
            "duration": item.get("duration"),
            "subtitle": selected,
        }
        if not selected:
            record["error"] = "no subtitle_url"
            outputs.append(record)
            continue
        stem = f"p{int(item['page']):02d}_{item['cid']}_{safe_slug(selected.get('lan') or 'ai-zh')}"
        try:
            payload = fetch_json(selected["subtitle_url"], meta.get("referer") or "https://www.bilibili.com/")
            record["files"] = write_subtitle_outputs(payload, subtitle_dir, stem)
            print(f"p{int(item['page']):02d}: lines={record['files']['line_count']} {item.get('part')}", flush=True)
        except Exception as exc:
            record["error"] = str(exc)
            print(f"p{int(item['page']):02d}: ERROR {exc}", flush=True)
        outputs.append(record)
        time.sleep(0.12)

    manifest = {
        **meta,
        "count": len(outputs),
        "downloaded": sum(1 for item in outputs if item.get("files")),
        "outputs": outputs,
    }
    (out_root / "browser_ai_subtitle_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"downloaded={manifest['downloaded']} out={out_root}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
