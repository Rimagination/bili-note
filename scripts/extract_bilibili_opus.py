#!/usr/bin/env python3
"""Extract Bilibili opus/article pages into Markdown, JSONL evidence, and images."""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any


TZ = timezone(timedelta(hours=8))
SCRIPT_DIR = Path(__file__).resolve().parent


def configure_stdout() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")


configure_stdout()


def headers(opus_id: str | None = None) -> dict[str, str]:
    referer = "https://www.bilibili.com/"
    if opus_id:
        referer = f"https://www.bilibili.com/opus/{opus_id}"
    return {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"
        ),
        "Referer": referer,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }


def normalize_url(url: str) -> str:
    if not url:
        return ""
    if url.startswith("//"):
        return "https:" + url
    if url.startswith("http://i") and ".hdslb.com/" in url:
        return "https://" + url[len("http://") :]
    return url


def extract_opus_id(source: str) -> str:
    match = re.search(r"(?:opus|dynamic)/(\d+)", source)
    if not match:
        match = re.search(r"\b(\d{12,})\b", source)
    if not match:
        raise ValueError(f"Could not find Bilibili opus id in: {source}")
    return match.group(1)


def clean_filename(value: str, limit: int = 90) -> str:
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", value).strip(" ._")
    return (value[:limit] or "untitled").strip(" ._")


def request_text(url: str, opus_id: str) -> str:
    req = urllib.request.Request(url, headers=headers(opus_id))
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8", errors="replace")


def extract_json_after_marker(text: str, marker: str) -> dict[str, Any]:
    start = text.find(marker)
    if start < 0:
        raise RuntimeError(f"Could not find {marker!r} in Bilibili opus page")
    start += len(marker)
    while start < len(text) and text[start].isspace():
        start += 1
    if start >= len(text) or text[start] != "{":
        raise RuntimeError("Initial state marker was found but JSON object did not follow")

    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return json.loads(text[start : index + 1])
    raise RuntimeError("Could not locate the end of Bilibili opus initial state JSON")


def fetch_initial_state(source: str) -> dict[str, Any]:
    opus_id = extract_opus_id(source)
    url = f"https://www.bilibili.com/opus/{opus_id}"
    html = request_text(url, opus_id)
    return extract_json_after_marker(html, "window.__INITIAL_STATE__=")


def node_text(node: dict[str, Any]) -> str:
    word = node.get("word")
    if isinstance(word, dict):
        return str(word.get("words") or "")
    rich = node.get("rich")
    if isinstance(rich, dict):
        return str(rich.get("text") or rich.get("orig_text") or "")
    user = node.get("user")
    if isinstance(user, dict):
        name = user.get("name") or user.get("uname") or ""
        return f"@{name}" if name else ""
    formula = node.get("formula")
    if isinstance(formula, dict):
        return str(formula.get("latex") or formula.get("text") or "")
    return ""


def nodes_text(nodes: list[dict[str, Any]] | None) -> str:
    return "".join(node_text(node) for node in nodes or [])


def paragraph_text(paragraph: dict[str, Any]) -> str:
    text = paragraph.get("text")
    if isinstance(text, dict):
        return nodes_text(text.get("nodes")).strip()
    heading = paragraph.get("heading")
    if isinstance(heading, dict):
        return nodes_text(heading.get("nodes")).strip()
    code = paragraph.get("code")
    if isinstance(code, dict):
        return str(code.get("content") or "").strip()
    return ""


def list_children_to_markdown(children: list[dict[str, Any]], ordered: bool, level: int = 0) -> list[str]:
    lines: list[str] = []
    for idx, child in enumerate(children, 1):
        child_level = int(child.get("level") or level + 1)
        indent = "  " * max(0, child_level - 1)
        marker = f"{int(child.get('order') or idx)}." if ordered else "-"
        parts = []
        for para in child.get("children") or []:
            rendered, _ = render_paragraph(para, [], collect_images=False)
            rendered = rendered.strip()
            if rendered:
                parts.append(rendered.replace("\n", " "))
        text = " ".join(parts).strip()
        if text:
            lines.append(f"{indent}{marker} {text}")
        nested = child.get("children") or []
        for para in nested:
            nested_list = para.get("list") if isinstance(para, dict) else None
            if isinstance(nested_list, dict) and nested_list.get("children"):
                lines.extend(list_children_to_markdown(nested_list.get("children") or [], ordered, child_level))
    return lines


def image_filename(index: int, url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    suffix = Path(parsed.path).suffix.lower()
    if suffix not in {".jpg", ".jpeg", ".png", ".webp", ".gif"}:
        suffix = ".jpg"
    return f"image_{index:03d}{suffix}"


def render_link_card(card: dict[str, Any]) -> str:
    card_type = card.get("type") or "link"
    for key in ("eva3_video", "eva3_opus", "common", "ugc", "opus"):
        value = card.get(key)
        if not isinstance(value, dict):
            continue
        info = value.get("info") if isinstance(value.get("info"), dict) else value
        title = info.get("title") or info.get("desc") or card_type
        jump_url = normalize_url(info.get("jump_url") or info.get("url") or info.get("uri") or "")
        if jump_url:
            return f"[{title}]({jump_url})"
        return str(title)
    return str(card_type)


def render_paragraph(
    paragraph: dict[str, Any],
    images: list[dict[str, Any]],
    collect_images: bool = True,
) -> tuple[str, str]:
    para_type = paragraph.get("para_type")
    if para_type == 1:
        text = paragraph_text(paragraph)
        return (text, text) if text else ("", "")
    if para_type == 8:
        heading = paragraph.get("heading") or {}
        level = max(1, min(6, int(heading.get("level") or 2)))
        text = paragraph_text(paragraph)
        return (f"{'#' * level} {text}" if text else "", text)
    if para_type == 7:
        code = paragraph.get("code") or {}
        lang = str(code.get("lang") or "").strip()
        content = str(code.get("content") or "").rstrip()
        if not content:
            return "", ""
        return f"```{lang}\n{content}\n```", content
    if para_type == 2:
        pics = ((paragraph.get("pic") or {}).get("pics") or [])
        lines = []
        text_parts = []
        for pic in pics:
            url = normalize_url(str(pic.get("url") or ""))
            if not url:
                continue
            if collect_images:
                index = len(images) + 1
                images.append(
                    {
                        "index": index,
                        "url": url,
                        "width": pic.get("width"),
                        "height": pic.get("height"),
                        "size": pic.get("size"),
                        "comment": pic.get("comment") or "",
                        "filename": image_filename(index, url),
                    }
                )
            else:
                index = len(images) + len(lines) + 1
            alt = str(pic.get("comment") or f"图片 {index}").strip()
            lines.append(f"![{alt}]({url})")
            text_parts.append(f"[图片 {index}] {alt} {url}".strip())
        return "\n".join(lines), "\n".join(text_parts)
    if para_type == 5:
        list_obj = paragraph.get("list") or {}
        ordered = int(list_obj.get("style") or 0) == 1
        lines = list_children_to_markdown(list_obj.get("children") or [], ordered)
        text = "\n".join(re.sub(r"^\s*(?:[-*]|\d+\.)\s*", "", line).strip() for line in lines)
        return "\n".join(lines), text
    if para_type == 6:
        card = ((paragraph.get("link_card") or {}).get("card") or {})
        rendered = render_link_card(card)
        return rendered, rendered
    return "", paragraph_text(paragraph)


def collect_modules(detail: dict[str, Any]) -> dict[str, Any]:
    modules = detail.get("modules") or []
    result: dict[str, Any] = {"modules": modules}
    for module in modules:
        module_type = module.get("module_type")
        if module_type == "MODULE_TYPE_TITLE":
            result["title"] = ((module.get("module_title") or {}).get("text") or "").strip()
        elif module_type == "MODULE_TYPE_AUTHOR":
            result["author"] = module.get("module_author") or {}
        elif module_type == "MODULE_TYPE_COLLECTION":
            result["collection"] = module.get("module_collection") or {}
        elif module_type == "MODULE_TYPE_TOPIC":
            result["topic"] = module.get("module_topic") or {}
        elif module_type == "MODULE_TYPE_CONTENT":
            result["paragraphs"] = (module.get("module_content") or {}).get("paragraphs") or []
        elif module_type == "MODULE_TYPE_STAT":
            result["stat"] = module.get("module_stat") or {}
        elif module_type == "MODULE_TYPE_COPYRIGHT":
            result["copyright"] = module.get("module_copyright") or {}
        elif module_type == "MODULE_TYPE_BOTTOM":
            result["bottom"] = module.get("module_bottom") or {}
    return result


def stat_count(stat: dict[str, Any], key: str) -> int:
    value = stat.get(key)
    if isinstance(value, dict):
        value = value.get("count")
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def to_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def fmt_ts(ts: Any) -> str:
    try:
        value = int(ts or 0)
    except (TypeError, ValueError):
        value = 0
    if not value:
        return ""
    return datetime.fromtimestamp(value, TZ).strftime("%Y-%m-%d %H:%M:%S")


def build_outputs(state: dict[str, Any], source: str) -> dict[str, Any]:
    detail = state.get("detail") or {}
    basic = detail.get("basic") or {}
    modules = collect_modules(detail)
    opus_id = str(detail.get("id_str") or state.get("id") or extract_opus_id(source))
    title = modules.get("title") or ((modules.get("bottom") or {}).get("share_info") or {}).get("title") or f"opus_{opus_id}"
    author = modules.get("author") or {}
    stat = modules.get("stat") or {}
    paragraphs = modules.get("paragraphs") or []
    images: list[dict[str, Any]] = []
    blocks: list[dict[str, Any]] = []
    markdown_lines = [f"# {title}", ""]
    plain_lines: list[str] = []

    for idx, paragraph in enumerate(paragraphs, 1):
        markdown, text = render_paragraph(paragraph, images)
        if not markdown and not text:
            continue
        block_type = {
            1: "text",
            2: "image",
            5: "list",
            6: "link_card",
            7: "code",
            8: "heading",
        }.get(paragraph.get("para_type"), f"para_{paragraph.get('para_type')}")
        blocks.append(
            {
                "block_id": f"O{opus_id}-B{idx:03d}",
                "index": idx,
                "type": block_type,
                "text": text,
                "markdown": markdown,
            }
        )
        if markdown:
            markdown_lines.extend([markdown, ""])
        if text:
            plain_lines.append(text)

    evidence = build_evidence(opus_id, blocks)
    content_chars = sum(len(line.strip()) for line in plain_lines)
    author_mid = str(author.get("mid") or "")
    pub_ts = author.get("pub_ts")
    normalized = {
        "source": f"https://www.bilibili.com/opus/{opus_id}",
        "input": source,
        "id_str": opus_id,
        "type": "opus",
        "basic": {
            "title": basic.get("title") or "",
            "article_type": basic.get("article_type"),
            "rid": str(basic.get("rid_str") or ""),
            "uid": str(basic.get("uid") or ""),
            "collection_id": str(basic.get("collection_id") or ""),
        },
        "comment": {
            "type": to_int(basic.get("comment_type")),
            "oid": str(basic.get("comment_id_str") or basic.get("rid_str") or ""),
        },
        "title": title,
        "author": {
            "name": author.get("name") or "",
            "mid": author_mid,
            "jump_url": normalize_url(author.get("jump_url") or ""),
            "pub_ts": pub_ts,
            "pub_time": author.get("pub_time") or fmt_ts(pub_ts),
        },
        "collection": modules.get("collection") or None,
        "topic": modules.get("topic") or None,
        "copyright": modules.get("copyright") or None,
        "stat": {
            "forward": stat_count(stat, "forward"),
            "comment": stat_count(stat, "comment"),
            "like": stat_count(stat, "like"),
            "coin": stat_count(stat, "coin"),
            "favorite": stat_count(stat, "favorite"),
        },
        "paragraph_count": len(paragraphs),
        "block_count": len(blocks),
        "image_count": len(images),
        "content_chars": content_chars,
    }
    metadata = {
        "data": {
            "id_str": opus_id,
            "type": "opus",
            "title": title,
            "owner": {"name": normalized["author"]["name"], "mid": author_mid},
            "pubdate": pub_ts,
            "duration": 0,
            "stat": {
                "view": 0,
                "reply": normalized["stat"]["comment"],
                "favorite": normalized["stat"]["favorite"],
                "coin": normalized["stat"]["coin"],
                "share": normalized["stat"]["forward"],
                "like": normalized["stat"]["like"],
                "danmaku": 0,
            },
        },
        "opus": normalized,
    }
    return {
        "normalized": normalized,
        "metadata": metadata,
        "blocks": blocks,
        "evidence": evidence,
        "images": images,
        "markdown": "\n".join(markdown_lines).rstrip() + "\n",
        "plain_text": "\n\n".join(plain_lines).strip() + "\n",
    }


def load_video_extractor() -> Any:
    script = SCRIPT_DIR / "extract_bilibili.py"
    spec = importlib.util.spec_from_file_location("extract_bilibili", script)
    module = importlib.util.module_from_spec(spec)
    if spec.loader is None:
        raise RuntimeError(f"Could not load {script}")
    spec.loader.exec_module(module)
    return module


def fetch_opus_comments(outputs: dict[str, Any], out_dir: Path) -> dict[str, Any]:
    normalized = outputs["normalized"]
    comment = normalized.get("comment") or {}
    target_type = to_int(comment.get("type"))
    oid = str(comment.get("oid") or "")
    if not target_type or not oid:
        raise RuntimeError("Bilibili opus page did not expose comment_type/comment_id_str")
    extractor = load_video_extractor()
    return extractor.fetch_comments(
        oid,
        None,
        out_dir,
        target_type=target_type,
        source=normalized["source"],
    )


def build_evidence(opus_id: str, blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    evidence: list[dict[str, Any]] = []
    chunk_lines: list[str] = []
    chunk_block_ids: list[str] = []
    chunk_no = 0

    def flush() -> None:
        nonlocal chunk_lines, chunk_block_ids, chunk_no
        text = "\n".join(line for line in chunk_lines if line.strip()).strip()
        if not text:
            chunk_lines = []
            chunk_block_ids = []
            return
        chunk_no += 1
        evidence.append(
            {
                "type": "opus_evidence",
                "evidence_id": f"O{opus_id}-E{chunk_no:03d}",
                "opus_id": opus_id,
                "block_ids": chunk_block_ids,
                "text": text,
            }
        )
        chunk_lines = []
        chunk_block_ids = []

    for block in blocks:
        text = str(block.get("text") or "").strip()
        if not text:
            continue
        if block.get("type") == "heading" and chunk_lines:
            flush()
        chunk_lines.append(text)
        chunk_block_ids.append(str(block.get("block_id")))
        if sum(len(line) for line in chunk_lines) >= 900 or len(chunk_lines) >= 12:
            flush()
    flush()
    return evidence


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def jsonl_line(data: dict[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"))


def download_images(images: list[dict[str, Any]], out_dir: Path, opus_id: str, force: bool = False) -> None:
    image_dir = out_dir / "images"
    image_dir.mkdir(parents=True, exist_ok=True)
    for image in images:
        filename = str(image.get("filename") or image_filename(int(image.get("index") or 0), image.get("url") or ""))
        path = image_dir / filename
        image["path"] = str(path)
        if path.exists() and not force:
            image["downloaded"] = True
            continue
        req = urllib.request.Request(str(image["url"]), headers=headers(opus_id))
        try:
            with urllib.request.urlopen(req, timeout=45) as resp:
                path.write_bytes(resp.read())
            image["downloaded"] = True
            time.sleep(0.08)
        except Exception as exc:
            image["downloaded"] = False
            image["error"] = str(exc)


def write_outputs(out_dir: Path, state: dict[str, Any], outputs: dict[str, Any], download: bool, force: bool) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    opus_id = outputs["normalized"]["id_str"]
    if download:
        download_images(outputs["images"], out_dir, opus_id, force)

    write_json(out_dir / "opus_raw.json", state)
    write_json(out_dir / "opus_normalized.json", outputs["normalized"])
    write_json(out_dir / "metadata.json", outputs["metadata"])
    write_json(out_dir / "images_manifest.json", {"opus_id": opus_id, "images": outputs["images"]})
    (out_dir / "article_content.md").write_text(outputs["markdown"], encoding="utf-8")
    (out_dir / "article_content.txt").write_text(outputs["plain_text"], encoding="utf-8")
    (out_dir / "article_content.jsonl").write_text(
        "\n".join(jsonl_line(block) for block in outputs["blocks"]) + ("\n" if outputs["blocks"] else ""),
        encoding="utf-8",
    )
    (out_dir / "article_evidence.jsonl").write_text(
        "\n".join(jsonl_line(item) for item in outputs["evidence"]) + ("\n" if outputs["evidence"] else ""),
        encoding="utf-8",
    )

    source_lines = [
        f"# {outputs['normalized']['title']}",
        "",
        f"- URL: {outputs['normalized']['source']}",
        f"- Opus ID: {opus_id}",
        f"- UP: {outputs['normalized']['author'].get('name', '')}",
        f"- Published: {outputs['normalized']['author'].get('pub_time', '')}",
        f"- Images: {outputs['normalized']['image_count']}",
        f"- Content chars: {outputs['normalized']['content_chars']}",
        "",
    ]
    (out_dir / "source.md").write_text("\n".join(source_lines), encoding="utf-8")
    summary = {
        "kind": "opus",
        "opus_id": opus_id,
        "title": outputs["normalized"]["title"],
        "source": outputs["normalized"]["source"],
        "metadata": str(out_dir / "metadata.json"),
        "article_content_md": str(out_dir / "article_content.md"),
        "article_content_jsonl": str(out_dir / "article_content.jsonl"),
        "article_evidence_jsonl": str(out_dir / "article_evidence.jsonl"),
        "images_manifest": str(out_dir / "images_manifest.json"),
        "image_count": outputs["normalized"]["image_count"],
        "downloaded_images": sum(1 for image in outputs["images"] if image.get("downloaded")),
        "content_chars": outputs["normalized"]["content_chars"],
        "evidence_blocks": len(outputs["evidence"]),
    }
    write_json(out_dir / "run_summary.json", summary)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", help="Bilibili opus URL or opus id")
    parser.add_argument("--out", required=True, help="Output directory")
    parser.add_argument("--download-images", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--comments", action="store_true", help="Fetch opus comments and child replies")
    parser.add_argument("--force", action="store_true", help="Re-download existing image files")
    args = parser.parse_args()

    state = fetch_initial_state(args.source)
    outputs = build_outputs(state, args.source)
    summary = write_outputs(Path(args.out), state, outputs, args.download_images, args.force)
    if args.comments:
        comments = fetch_opus_comments(outputs, Path(args.out))
        summary["comments"] = {
            "target_type": comments.get("target_type"),
            "oid": comments.get("oid"),
            "top_level_count": comments.get("top_level_count"),
            "child_reply_count": comments.get("child_reply_count"),
            "total_fetched_comments": comments.get("total_fetched_comments"),
            "wbi_main_all_count": comments.get("wbi_main_all_count"),
        }
        write_json(Path(args.out) / "run_summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
