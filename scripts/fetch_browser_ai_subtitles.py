"""Fetch Bilibili AI subtitles through an already-open logged-in browser page.

Chrome uses the web-access CDP proxy; Edge can use its direct CDP endpoint.
Neither route reads browser cookies. Instead, it asks the Bilibili page to call
the same player API it uses:

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

from edge_cdp import DirectCdpSession, EdgeCdpError, select_target


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


class ProxyCdpSession:
    """Adapter for the existing web-access proxy API."""

    def __init__(self, cdp_base: str, target: str) -> None:
        self.cdp_base = cdp_base
        self.target = target

    def evaluate(self, expression: str, timeout: int = 45) -> dict:
        try:
            return cdp_eval(self.cdp_base, self.target, expression, timeout)
        except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
            raise EdgeCdpError(f"无法调用 web-access CDP 代理：{exc}") from exc

    def close(self) -> None:
        return None


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


def subtitle_url(subtitle: dict) -> str:
    return str(subtitle.get("subtitle_url") or subtitle.get("subtitle_url_v2") or "")


def select_subtitle(item: dict) -> tuple[dict | None, str]:
    for candidate in item.get("subtitles", []):
        if not isinstance(candidate, dict):
            continue
        url = subtitle_url(candidate)
        if url:
            selected = dict(candidate)
            selected["resolved_subtitle_url"] = url
            if not selected.get("subtitle_url"):
                selected["subtitle_url"] = url
            return selected, url
    return None, ""


def page_catalog(session: ProxyCdpSession | DirectCdpSession) -> list[dict]:
    js = """
(() => {
  const state = window.__INITIAL_STATE__ || {};
  const pages = state.videoData?.pages || state.pages || [];
  return {
    pages: pages.map((p, index) => ({
      index,
      page: p.page,
      cid: p.cid,
      part: p.part,
      duration: p.duration
    })),
    title: document.title,
    url: location.href
  };
})()
""".strip()
    payload = session.evaluate(js)
    value = payload.get("value") or {}
    pages = value.get("pages")
    if not isinstance(pages, list) or not pages:
        raise EdgeCdpError(
            f"当前页面没有 B 站视频分P信息；请打开 B 站视频页，或传入正确的 --target。页面信息：{value}"
        )
    return [page for page in pages if isinstance(page, dict)]


def page_count(session: ProxyCdpSession | DirectCdpSession) -> int:
    return len(page_catalog(session))


def select_page_indexes(pages: list[dict], parts: str) -> list[int]:
    if not pages:
        return []
    if not parts or parts == "all":
        return [int(page["index"]) for page in pages]
    if parts == "key":
        pattern = re.compile(r"(Agentic|Summary|总结|实操|打造|冠军|方案|Challenge|打卡)", re.I)
        selected = [page for page in pages if pattern.search(str(page.get("part") or ""))]
        selected = selected or pages[:1]
        return [int(page["index"]) for page in selected]
    try:
        wanted = {int(value.strip()) for value in parts.split(",") if value.strip()}
    except ValueError as exc:
        raise EdgeCdpError(f"--parts 无效：{parts}；请使用 all、key 或逗号分隔的分P编号。") from exc
    selected = [page for page in pages if int(page.get("page") or 0) in wanted]
    if not selected:
        raise EdgeCdpError(f"--parts 没有匹配到分P：{parts}。")
    return [int(page["index"]) for page in selected]


def fetch_url_batch(
    session: ProxyCdpSession | DirectCdpSession,
    indexes: list[int],
    sleep_ms: int,
) -> dict:
    indexes_json = json.dumps(indexes)
    js = f"""
(async () => {{
  const state = window.__INITIAL_STATE__ || {{}};
  const aid = state.aid || state.arc?.aid || state.videoData?.aid;
  const bvid = state.bvid || state.videoData?.bvid;
  const referer = location.href;
  const allPages = state.videoData?.pages || state.pages || [];
  const indexes = {indexes_json};
  const pages = indexes.map(index => allPages[index]).filter(Boolean);
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
  return {{ aid, bvid, referer, indexes, results }};
}})()
""".strip()
    payload = session.evaluate(js, timeout=60)
    value = payload.get("value")
    if not isinstance(value, dict):
        raise EdgeCdpError("B 站页面没有返回可用的字幕接口结果。请确认页面已加载完成。")
    return value


def write_subtitle_outputs(payload: dict, out_dir: Path, stem: str) -> dict:
    out_dir = out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
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
    parser.add_argument("--target", help="CDP target id of an open Bilibili video tab")
    parser.add_argument("--out", required=True, help="Output directory")
    parser.add_argument(
        "--browser",
        choices=["chrome", "edge"],
        default="chrome",
        help="Browser connection: Chrome uses web-access; Edge uses its direct CDP endpoint",
    )
    parser.add_argument("--cdp-base", default="http://localhost:3456", help="web-access CDP proxy base URL")
    parser.add_argument(
        "--edge-cdp-url",
        default="http://127.0.0.1:9222",
        help="Edge remote-debugging HTTP endpoint, used with --browser edge",
    )
    parser.add_argument("--parts", default="all", help="all, key, or comma-separated page numbers")
    parser.add_argument("--batch-size", type=int, default=6)
    parser.add_argument("--sleep-ms", type=int, default=150)
    parser.add_argument("--limit", type=int, default=0, help="Optional max parts to fetch, 0 means all")
    args = parser.parse_args()

    out_root = Path(args.out).resolve()
    subtitle_dir = out_root / "browser_ai_subtitles"
    subtitle_dir.mkdir(parents=True, exist_ok=True)

    session: ProxyCdpSession | DirectCdpSession | None = None
    try:
        if args.browser == "edge":
            target_info = select_target(args.edge_cdp_url, args.target)
            target = str(target_info.get("targetId") or target_info.get("id"))
            session = DirectCdpSession(target_info)
        else:
            if not args.target:
                raise EdgeCdpError("Chrome 路线需要 --target；请先从 web-access /targets 获取 B 站页面 target。")
            target = args.target
            session = ProxyCdpSession(args.cdp_base, target)

        pages = page_catalog(session)
        indexes = select_page_indexes(pages, args.parts)
        if args.limit > 0:
            indexes = indexes[: args.limit]
        if not indexes:
            raise EdgeCdpError("没有选中的视频分P。")

        all_results = []
        meta = {}
        for start in range(0, len(indexes), args.batch_size):
            batch_indexes = indexes[start : start + args.batch_size]
            batch = fetch_url_batch(session, batch_indexes, args.sleep_ms)
            meta = {k: batch.get(k) for k in ("aid", "bvid", "referer")}
            all_results.extend(batch["results"])
            with_url = sum(
                1 for item in all_results if any(subtitle_url(s) for s in item.get("subtitles", []))
            )
            print(
                f"batch {start + 1}-{start + len(batch_indexes)}: collected={len(all_results)} with_url={with_url}",
                flush=True,
            )
            time.sleep(0.35)

        url_manifest = {
            **meta,
            "browser": args.browser,
            "target": target,
            "parts": args.parts,
            "count": len(all_results),
            "with_url": sum(1 for item in all_results if any(subtitle_url(s) for s in item.get("subtitles", []))),
            "results": all_results,
        }
        (out_root / "browser_ai_subtitle_urls.json").write_text(
            json.dumps(url_manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        outputs = []
        for item in all_results:
            selected, resolved_url = select_subtitle(item)
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
                payload = fetch_json(resolved_url, meta.get("referer") or "https://www.bilibili.com/")
                record["files"] = write_subtitle_outputs(payload, subtitle_dir, stem)
                print(f"p{int(item['page']):02d}: lines={record['files']['line_count']} {item.get('part')}", flush=True)
            except Exception as exc:
                record["error"] = str(exc)
                print(f"p{int(item['page']):02d}: ERROR {exc}", flush=True)
            outputs.append(record)
            time.sleep(0.12)

        manifest = {
            **meta,
            "browser": args.browser,
            "target": target,
            "parts": args.parts,
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
    except (EdgeCdpError, ValueError, KeyError, TypeError) as exc:
        raise SystemExit(f"浏览器字幕提取失败：{exc}") from exc
    finally:
        if session:
            session.close()


if __name__ == "__main__":
    raise SystemExit(main())
