"""
作品說明抓取工具
從 YouTube Data API v3、Vimeo oEmbed API、頁面 meta 標籤抓取作品說明

用法：
    python scripts/description_fetcher.py             # 抓全部
    python scripts/description_fetcher.py --gp-gold   # 只抓 Grand Prix + Gold
    python scripts/description_fetcher.py --year 2024 # 只抓特定年份

需要環境變數：
    YOUTUBE_API_KEY  → Google Cloud Console 建立的 API 金鑰
"""

import argparse
import json
import os
import re
import time
from pathlib import Path
from urllib.parse import urlparse, parse_qs

import requests
from bs4 import BeautifulSoup

# ──────────────────────────────────────────────
# 設定
# ──────────────────────────────────────────────

BASE_DIR = Path(__file__).parent.parent
DATA_PATH = BASE_DIR / "docs" / "data" / "cannes_winners.json"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/121.0.0.0 Safari/537.36"
    )
}

YOUTUBE_API_KEY = os.environ.get("YOUTUBE_API_KEY", "")
SAVE_EVERY = 50   # 每 N 筆存一次
REQUEST_DELAY = 1  # 秒（避免 rate limit）

GP_GOLD_LEVELS = {"grand prix", "titanium", "gold"}

# ──────────────────────────────────────────────
# YouTube
# ──────────────────────────────────────────────

def extract_youtube_id(url: str) -> str | None:
    """從各種 YouTube URL 格式提取 video ID"""
    patterns = [
        r"(?:youtube\.com/watch\?v=|youtu\.be/)([A-Za-z0-9_-]{11})",
        r"youtube\.com/embed/([A-Za-z0-9_-]{11})",
        r"youtube\.com/shorts/([A-Za-z0-9_-]{11})",
    ]
    for p in patterns:
        m = re.search(p, url)
        if m:
            return m.group(1)
    return None


def fetch_youtube_description(video_ids: list[str]) -> dict[str, str]:
    """批次抓取 YouTube 影片說明（每次最多 50 個）"""
    if not YOUTUBE_API_KEY:
        return {}

    results = {}
    # YouTube API 每次最多 50 個
    for i in range(0, len(video_ids), 50):
        batch = video_ids[i:i+50]
        url = "https://www.googleapis.com/youtube/v3/videos"
        params = {
            "part": "snippet",
            "id": ",".join(batch),
            "key": YOUTUBE_API_KEY,
            "fields": "items(id,snippet(description))",
        }
        try:
            r = requests.get(url, params=params, timeout=15)
            r.raise_for_status()
            data = r.json()
            for item in data.get("items", []):
                vid = item["id"]
                desc = item.get("snippet", {}).get("description", "").strip()
                if desc:
                    results[vid] = desc[:500]  # 截斷至 500 字元
        except Exception as e:
            print(f"  ⚠ YouTube API 錯誤：{e}")
        time.sleep(0.5)

    return results


# ──────────────────────────────────────────────
# Vimeo
# ──────────────────────────────────────────────

def extract_vimeo_id(url: str) -> str | None:
    """從 Vimeo URL 提取 video ID"""
    m = re.search(r"vimeo\.com/(?:video/)?(\d+)", url)
    return m.group(1) if m else None


def fetch_vimeo_description(url: str) -> str:
    """用 oEmbed API 抓 Vimeo 影片說明（不需要 API key）"""
    try:
        r = requests.get(
            "https://vimeo.com/api/oembed.json",
            params={"url": url},
            timeout=10,
            headers=HEADERS,
        )
        if r.status_code == 200:
            data = r.json()
            desc = data.get("description", "").strip()
            return desc[:500] if desc else ""
    except Exception:
        pass
    return ""


# ──────────────────────────────────────────────
# 通用 Meta 標籤抓取
# ──────────────────────────────────────────────

def fetch_meta_description(url: str) -> str:
    """抓取頁面的 og:description 或 meta description"""
    if not url or url.startswith("mailto"):
        return ""
    try:
        r = requests.get(url, headers=HEADERS, timeout=10, allow_redirects=True)
        if r.status_code != 200:
            return ""
        soup = BeautifulSoup(r.text, "lxml")

        # 優先 og:description
        og = soup.find("meta", property="og:description")
        if og and og.get("content"):
            return og["content"].strip()[:500]

        # 次選 name="description"
        meta = soup.find("meta", attrs={"name": "description"})
        if meta and meta.get("content"):
            return meta["content"].strip()[:500]

    except Exception:
        pass
    return ""


# ──────────────────────────────────────────────
# 主要抓取邏輯
# ──────────────────────────────────────────────

def fetch_descriptions(entries: list[dict], filter_gp_gold: bool = False) -> list[dict]:
    """為每筆條目抓取說明，回傳更新後的 entries"""

    # 篩選需要處理的條目
    targets = []
    for i, e in enumerate(entries):
        if e.get("description_en"):
            continue  # 已有說明，跳過
        if filter_gp_gold and e.get("award_level", "").lower() not in GP_GOLD_LEVELS:
            continue
        if not e.get("original_url"):
            continue
        targets.append((i, e))

    total = len(targets)
    print(f"需要抓取說明：{total} 筆")

    if not targets:
        print("所有條目已有說明，無需抓取。")
        return entries

    # ── YouTube 批次抓取 ──
    yt_map = {}  # index → video_id
    yt_ids = []
    for i, e in targets:
        vid = extract_youtube_id(e.get("original_url", ""))
        if vid:
            yt_map[i] = vid
            yt_ids.append(vid)

    if yt_ids and YOUTUBE_API_KEY:
        print(f"YouTube 批次抓取 {len(yt_ids)} 支影片...")
        yt_desc = fetch_youtube_description(list(set(yt_ids)))
        print(f"  取得 {len(yt_desc)} 筆說明")
    elif yt_ids and not YOUTUBE_API_KEY:
        print(f"⚠ 沒有 YOUTUBE_API_KEY，跳過 {len(yt_ids)} 筆 YouTube 條目")
        yt_desc = {}
    else:
        yt_desc = {}

    # ── 逐筆處理 ──
    saved_count = 0
    for progress, (i, e) in enumerate(targets, 1):
        url = e.get("original_url", "")
        desc = ""

        if i in yt_map:
            # YouTube
            desc = yt_desc.get(yt_map[i], "")
            if not desc:
                # API 沒拿到，不再 fallback（避免浪費時間）
                pass

        elif "vimeo.com" in url:
            # Vimeo oEmbed
            print(f"  [{progress}/{total}] Vimeo: {e.get('campaign_name', '')[:40]}...")
            desc = fetch_vimeo_description(url)
            time.sleep(REQUEST_DELAY)

        else:
            # 通用 meta 抓取（DandAD, Contagious 等）
            print(f"  [{progress}/{total}] Meta: {url[:60]}...")
            desc = fetch_meta_description(url)
            time.sleep(REQUEST_DELAY)

        if desc:
            entries[i]["description_en"] = desc
            saved_count += 1
            if progress % 10 == 0 or i in yt_map:
                print(f"  [{progress}/{total}] ✓ {e.get('campaign_name', '')[:30]} — {desc[:60]}...")

        # 斷點存檔
        if saved_count > 0 and saved_count % SAVE_EVERY == 0:
            save_json(entries)
            print(f"  💾 存檔（已取得 {saved_count} 筆說明）")

    return entries


def save_json(entries: list[dict]):
    with open(DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(entries, f, ensure_ascii=False, indent=2)


# ──────────────────────────────────────────────
# 主程式
# ──────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="作品說明抓取工具")
    parser.add_argument("--gp-gold", action="store_true", help="只抓 Grand Prix + Gold")
    parser.add_argument("--year", type=int, help="只抓特定年份")
    args = parser.parse_args()

    if not DATA_PATH.exists():
        print(f"✗ 找不到資料檔：{DATA_PATH}")
        return

    if not YOUTUBE_API_KEY:
        print("⚠ 未設定 YOUTUBE_API_KEY 環境變數，YouTube 說明將無法抓取")
        print("  請在 Codespace 設定：export YOUTUBE_API_KEY=你的金鑰")

    print(f"讀取資料：{DATA_PATH}")
    with open(DATA_PATH, encoding="utf-8") as f:
        entries = json.load(f)

    if args.year:
        indices = [i for i, e in enumerate(entries) if e.get("year") == args.year]
        print(f"篩選年份 {args.year}：{len(indices)} 筆")
        # 只處理這些 index
        subset = [(i, entries[i]) for i in indices if not entries[i].get("description_en")]
        # 用臨時邏輯處理（重用 fetch_descriptions 邏輯）
        temp = [e for i, e in enumerate(entries) if e.get("year") == args.year]
        temp = fetch_descriptions(temp, filter_gp_gold=args.gp_gold)
        for j, i in enumerate([i for i, e in enumerate(entries) if e.get("year") == args.year]):
            entries[i] = temp[j]
    else:
        entries = fetch_descriptions(entries, filter_gp_gold=args.gp_gold)

    save_json(entries)

    total_desc = sum(1 for e in entries if e.get("description_en"))
    print(f"\n完成！共 {total_desc} / {len(entries)} 筆有說明。")


if __name__ == "__main__":
    main()
