"""
作品說明抓取工具 v4

來源策略：
  Vimeo  → Vimeo oEmbed API（免費，任何 IP 可用，返回真實說明）
  YouTube → YouTube Data API v3（免費 10,000次/天，需設定 YOUTUBE_API_KEY 環境變數）
            若無 API key → 跳過（og:description 從 Azure IP 只拿到通用文字，無意義）
  其他   → og:description / meta description（DandAD、Contagious、agency 官網等）

用法：
    python scripts/description_fetcher.py             # 抓全部
    python scripts/description_fetcher.py --gp-gold   # 只抓 Grand Prix + Gold
    python scripts/description_fetcher.py --year 2024 # 只抓特定年份
    python scripts/description_fetcher.py --test 5    # 測試前 N 筆
    python scripts/description_fetcher.py --retry     # 重試空白的 YouTube 條目
                                                      # （通常在設定好 YOUTUBE_API_KEY 後使用）

YouTube API 設定：
    在 Codespaces 終端機執行：
    export YOUTUBE_API_KEY="AIza..."
"""

import argparse
import json
import os
import re
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

# ──────────────────────────────────────────────
# 設定
# ──────────────────────────────────────────────

BASE_DIR  = Path(__file__).parent.parent
DATA_PATH = BASE_DIR / "docs" / "data" / "cannes_winners.json"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

REQUEST_DELAY   = 0.5   # 秒（Vimeo oEmbed / 一般網頁）
YT_API_DELAY    = 0.1   # 秒（YouTube Data API 回應快，不需太長間隔）
SAVE_EVERY      = 50
GP_GOLD_LEVELS  = {"grand prix", "titanium", "gold"}

# YouTube og:description 從 Azure IP 拿到的通用無用文字（需過濾）
YOUTUBE_GENERIC_PREFIXES = (
    "Enjoy the videos and music you love",
    "Share your videos with friends, family",
    "YouTube のサービスについて",  # 日文頁面
)

# ──────────────────────────────────────────────
# URL 辨識
# ──────────────────────────────────────────────

def extract_youtube_id(url: str) -> str | None:
    """從 YouTube URL 抽出 video ID。"""
    m = re.search(r"(?:youtube\.com/watch\?.*?v=|youtu\.be/)([a-zA-Z0-9_-]{11})", url)
    return m.group(1) if m else None


def extract_vimeo_id(url: str) -> str | None:
    """從 Vimeo URL 抽出 video ID。"""
    m = re.search(r"vimeo\.com/(?:video/)?(\d+)", url)
    return m.group(1) if m else None


# ──────────────────────────────────────────────
# 各來源抓取函式
# ──────────────────────────────────────────────

def fetch_vimeo(url: str) -> str:
    """Vimeo oEmbed API — 任何 IP 均可用，返回真實影片說明。"""
    try:
        api_url = f"https://vimeo.com/api/oembed.json?url={url}"
        resp = requests.get(api_url, headers=HEADERS, timeout=12)
        if resp.status_code == 200:
            data = resp.json()
            desc = (data.get("description") or "").strip()
            return desc[:500] if desc else ""
    except Exception:
        pass
    return ""


def fetch_youtube_api(video_id: str, api_key: str) -> str:
    """YouTube Data API v3 — 需要 API key，返回完整影片說明。"""
    try:
        api_url = (
            f"https://www.googleapis.com/youtube/v3/videos"
            f"?id={video_id}&key={api_key}&part=snippet"
        )
        resp = requests.get(api_url, timeout=10)
        if resp.status_code == 200:
            items = resp.json().get("items", [])
            if items:
                desc = (items[0]["snippet"].get("description") or "").strip()
                # 只取第一段（廣告說明通常第一段最重要）
                first_para = desc.split("\n\n")[0].strip()
                return first_para[:500] if first_para else ""
    except Exception:
        pass
    return ""


def fetch_og_description(url: str) -> str:
    """一般頁面的 og:description / meta description（非 YouTube/Vimeo 用）。"""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=12, allow_redirects=True)
        if resp.status_code != 200:
            return ""

        soup = BeautifulSoup(resp.text, "lxml")

        og = soup.find("meta", property="og:description")
        if og and og.get("content", "").strip():
            text = og["content"].strip()
            # 過濾 YouTube 通用文字（萬一 URL 被誤判為一般頁面）
            if any(text.startswith(p) for p in YOUTUBE_GENERIC_PREFIXES):
                return ""
            return text[:500]

        meta = soup.find("meta", attrs={"name": "description"})
        if meta and meta.get("content", "").strip():
            text = meta["content"].strip()
            if any(text.startswith(p) for p in YOUTUBE_GENERIC_PREFIXES):
                return ""
            return text[:500]

    except Exception:
        pass
    return ""


def fetch_description(url: str, yt_api_key: str) -> str:
    """根據 URL 類型選擇最佳抓取策略。"""
    if not url or url.startswith("mailto") or url.startswith("#"):
        return ""

    url_lower = url.lower()

    # ── Vimeo ──
    if "vimeo.com" in url_lower:
        return fetch_vimeo(url)

    # ── YouTube ──
    if "youtube.com" in url_lower or "youtu.be" in url_lower:
        if yt_api_key:
            vid_id = extract_youtube_id(url)
            if vid_id:
                time.sleep(YT_API_DELAY)
                return fetch_youtube_api(vid_id, yt_api_key)
        # 無 API key → 跳過（og:description 只拿到無用通用文字）
        return ""

    # ── 其他（DandAD, Contagious, agency 官網等）──
    return fetch_og_description(url)


# ──────────────────────────────────────────────
# 存檔
# ──────────────────────────────────────────────

def save(entries: list[dict]):
    with open(DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(entries, f, ensure_ascii=False, indent=2)


# ──────────────────────────────────────────────
# 主要邏輯
# ──────────────────────────────────────────────

def run(entries: list[dict],
        filter_gp_gold: bool,
        filter_year: int | None,
        test_n: int | None,
        retry_youtube: bool,
        yt_api_key: str) -> list[dict]:

    def needs_fetch(e: dict) -> bool:
        has_desc = bool(e.get("description_en"))
        has_url  = bool(e.get("original_url"))
        if not has_url:
            return False
        if filter_gp_gold and e.get("award_level", "").lower() not in GP_GOLD_LEVELS:
            return False
        if filter_year and e.get("year") != filter_year:
            return False
        if retry_youtube:
            # --retry 模式：只重試 YouTube 且目前無說明的條目
            url = e.get("original_url", "")
            is_yt = "youtube.com" in url.lower() or "youtu.be" in url.lower()
            return is_yt and not has_desc
        return not has_desc

    targets = [i for i, e in enumerate(entries) if needs_fetch(e)]

    if test_n:
        targets = targets[:test_n]

    total = len(targets)
    print(f"待抓取：{total} 筆")
    if not total:
        print("全部已完成，無需重抓。")
        return entries

    yt_count   = sum(1 for i in targets
                     if "youtube" in entries[i].get("original_url","").lower()
                     or "youtu.be" in entries[i].get("original_url","").lower())
    vim_count  = sum(1 for i in targets
                     if "vimeo.com" in entries[i].get("original_url","").lower())
    other_count = total - yt_count - vim_count

    print(f"  YouTube：{yt_count} 筆（{'有 API key ✓' if yt_api_key else '無 API key，將跳過'}）")
    print(f"  Vimeo  ：{vim_count} 筆（oEmbed API ✓）")
    print(f"  其他   ：{other_count} 筆（og:description）")
    print()

    ok = fail = skip_yt = 0

    for progress, i in enumerate(targets, 1):
        e    = entries[i]
        url  = e["original_url"]
        name = e.get("campaign_name", "")[:35]

        # YouTube 無 key → 直接標記跳過
        url_lower = url.lower()
        is_yt = "youtube.com" in url_lower or "youtu.be" in url_lower
        if is_yt and not yt_api_key:
            entries[i]["description_en"] = ""
            skip_yt += 1
            if progress <= 5:
                print(f"  [{progress}/{total}] ⏭ {name} (YouTube，無 API key)")
            time.sleep(0)
            continue

        desc = fetch_description(url, yt_api_key)

        if not is_yt:   # YouTube API 已有自己的延遲
            time.sleep(REQUEST_DELAY)

        if desc:
            entries[i]["description_en"] = desc
            ok += 1
            if progress <= 5 or progress % 50 == 0:
                print(f"  [{progress}/{total}] ✓ {name}")
                print(f"    {desc[:90]}...")
        else:
            entries[i]["description_en"] = ""
            fail += 1
            if progress <= 5 or progress % 100 == 0:
                print(f"  [{progress}/{total}] ✗ {name[:40]} ({url[:50]})")

        if progress % SAVE_EVERY == 0:
            save(entries)
            effective = ok + fail - skip_yt
            pct = round(ok / effective * 100) if effective else 0
            print(f"  💾 [{progress}/{total}] 存檔 — "
                  f"成功率 {pct}%（✓{ok} ✗{fail} ⏭{skip_yt} YouTube跳過）")

    return entries


# ──────────────────────────────────────────────
# 主程式
# ──────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="作品說明抓取工具 v4")
    parser.add_argument("--gp-gold", action="store_true", help="只抓 Grand Prix + Gold")
    parser.add_argument("--year",    type=int,            help="只抓特定年份")
    parser.add_argument("--test",    type=int, metavar="N", help="只抓前 N 筆（測試用）")
    parser.add_argument("--retry",   action="store_true",
                        help="重試 YouTube 條目（設定好 YOUTUBE_API_KEY 後使用）")
    args = parser.parse_args()

    yt_api_key = os.environ.get("YOUTUBE_API_KEY", "").strip()

    if not DATA_PATH.exists():
        print(f"✗ 找不到 {DATA_PATH}，請先執行 scraper.py")
        return

    with open(DATA_PATH, encoding="utf-8") as f:
        entries = json.load(f)
    print(f"讀取 {len(entries)} 筆資料")

    if yt_api_key:
        print(f"YouTube Data API：已設定 ✓")
    else:
        print("YouTube Data API：未設定（YouTube 條目將跳過）")
        print("  → 如需抓取 YouTube 說明，請先執行：")
        print('     export YOUTUBE_API_KEY="你的API金鑰"')
    print()

    entries = run(entries,
                  filter_gp_gold=args.gp_gold,
                  filter_year=args.year,
                  test_n=args.test,
                  retry_youtube=args.retry,
                  yt_api_key=yt_api_key)
    save(entries)

    have    = sum(1 for e in entries if e.get("description_en"))
    have_yt = sum(1 for e in entries
                  if e.get("description_en")
                  and ("youtube" in e.get("original_url","").lower()
                       or "youtu.be" in e.get("original_url","").lower()))
    pct = round(have / len(entries) * 100)
    print(f"\n完成！{have} / {len(entries)} 筆有說明（{pct}%）")
    print(f"  其中 YouTube 有說明：{have_yt} 筆")

    if have > 0:
        print("\n下一步：python scripts/translator.py --gp-gold")
    if not yt_api_key:
        print("\n💡 提示：設定 YouTube Data API key 後執行 --retry 可補抓 YouTube 說明")
        print("   export YOUTUBE_API_KEY=\"AIza...\"")
        print("   python scripts/description_fetcher.py --gp-gold --retry")


if __name__ == "__main__":
    main()
