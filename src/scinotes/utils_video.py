"""Subtitle extraction for YouTube / Bilibili videos.

Uses yt-dlp first; falls back to Bilibili's public player API for B 站 videos.
"""

from __future__ import annotations

import json
import re

import httpx
import yt_dlp


def clean_subtitle(content: str, ext: str) -> str:
    ext = ext.lower()
    if ext == ".txt":
        return content.strip()
    if ext in (".json3", ".json"):
        return _clean_json_subtitle(content)
    return _clean_srt_vtt(content)


def _clean_json_subtitle(content: str) -> str:
    try:
        data = json.loads(content)
    except Exception:
        return content
    lines: list[str] = []
    if "events" in data:
        for event in data["events"]:
            segs = event.get("segs", [])
            text = "".join(s.get("utf8", "") for s in segs).strip()
            if text and text != "\n":
                lines.append(text)
    elif "body" in data:
        for item in data["body"]:
            text = item.get("content", "").strip()
            if text:
                lines.append(text)
    else:
        return content
    return _deduplicate_lines("\n".join(lines))


def _clean_srt_vtt(content: str) -> str:
    content = re.sub(r"^WEBVTT.*?\n\n", "", content, flags=re.DOTALL)
    content = re.sub(r"\d{2}:\d{2}:\d{2}[.,]\d{3}\s*-->\s*\d{2}:\d{2}:\d{2}[.,]\d{3}.*\n?", "", content)
    content = re.sub(r"^\d+\s*$", "", content, flags=re.MULTILINE)
    content = re.sub(r"<[^>]+>", "", content)
    content = re.sub(r"\n{3,}", "\n\n", content)
    return _deduplicate_lines(content.strip())


def _deduplicate_lines(text: str) -> str:
    lines = text.split("\n")
    deduped: list[str] = []
    prev = ""
    for line in lines:
        line = line.strip()
        if line and line != prev:
            deduped.append(line)
            prev = line
    return "\n".join(deduped)


def get_bilibili_sub(url: str) -> str | None:
    bv_match = re.search(r"(BV[\w]+)", url)
    if not bv_match:
        return None
    bvid = bv_match.group(1)
    headers = {"User-Agent": "Mozilla/5.0 scinotes"}

    try:
        with httpx.Client(timeout=10) as client:
            r1 = client.get(f"https://api.bilibili.com/x/player/pagelist?bvid={bvid}", headers=headers)
            data = r1.json()
            if data.get("code") != 0 or not data.get("data"):
                return None
            cid = data["data"][0]["cid"]

            r2 = client.get(f"https://api.bilibili.com/x/player/v2?bvid={bvid}&cid={cid}", headers=headers)
            data2 = r2.json()
            subtitles = data2.get("data", {}).get("subtitle", {}).get("subtitles", [])
            if not subtitles:
                return None

            sub_url = subtitles[0].get("subtitle_url", "")
            if sub_url.startswith("//"):
                sub_url = "https:" + sub_url
            if not sub_url:
                return None

            r3 = client.get(sub_url)
            return clean_subtitle(r3.text, ".json")
    except Exception:
        return None


def fetch_subtitle(url: str) -> str:
    ydl_opts = {
        "skip_download": True,
        "writesubtitles": True,
        "writeautomaticsub": True,
        "quiet": True,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        try:
            info = ydl.extract_info(url, download=False)
            subs = info.get("requested_subtitles")
            if subs:
                first_key = list(subs.keys())[0]
                sub_url = subs[first_key].get("url")
                ext = subs[first_key].get("ext", "vtt")
                if sub_url:
                    with httpx.Client(timeout=15) as client:
                        resp = client.get(sub_url)
                    return clean_subtitle(resp.text, ext)
        except Exception:
            pass

    if "bilibili.com" in url or "b23.tv" in url:
        result = get_bilibili_sub(url)
        if result:
            return result

    return "No subtitles found or this video does not support extraction."
