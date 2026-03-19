"""
作品說明抓取工具
- 影片連結（YouTube / Vimeo / 其他）→ yt-dlp（不下載影片，只抓 metadata）
- 其他連結（DandAD / Contagious 等）→ 抓頁面 og:description meta 標籤
- 完全不需要任何 API 金鑰

用法：
    python scripts/description_fetcher.py             # 抓全部
    python scripts/description_fetcher.py --gp-gold   # 只抓 Grand Prix + Gold
    python scripts/description_fetcher.py --year 2024 # 只抓特定年份
"""

import argparse
import json
import time
from pathlib import Path

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

SAVE_EVERY = 50
VIDEO_DOMAINS = ["youtube.com", "youtu.be", "vimeo.com", "dailymotion.com", "wistia.com"]
GP_GOLD_LEVELS = {"grand prix", "titanium", "gold"}

# ──────────────────────────────────────────────
# yt-dlp（影片 metadata 抓取）
# ──────────────────────────────────────────────

def fetch_video_description(url: str) -> str:
    """用 yt-dlp 抓影片說明（不下載影片）"""
    try:
        import yt_dlp
    except ImportError:
        print("✗ 找不到 yt-dlp，請執行：pip install yt-dlp")
        return ""

    ydl_opts = {
        "skip_download": True,
        "quiet": True,
        "no_warnings": True,
        "extract_flat": False,
        "socket_timeout": 15,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            if info:
                desc = info.get("description", "") or ""
                return desc.strip()[:500]
    except Exception as e:
        # 靜默失敗（影片已下架、地區限制等）
        pass

    return ""


# ──────────────────────────────────────────────
# 通用 Meta 標籤抓取（非影片頁面）
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


def is_video_url(url: str) -> bool:
    url_lower = url.lower()
    return any(d in url_lower for d in VIDEO_DOMAINS)


# ──────────────────────────────────────────────
# 存檔
# ──────────────────────────────────────────────

def save_json(entries: list[dict]):
    with open(DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(entries, f, ensure_ascii=False, indent=2)


# ──────────────────────────────────────────────
# 主要抓取邏輯
# ──────────────────────────────────────────────

def fetch_descriptions(entries: list[dict], filter_gp_gold: bool = False,
                       filter_year: int | None = None) -> list[dict]:

    targets = []
    for i, e in enumerate(entries):
        if e.get("description_en"):
            continue
        if filter_gp_gold and e.get("award_level", "").lower() not in GP_GOLD_LEVELS:
            continue
        if filter_year and e.get("year") != filter_year:
            continue
        if not e.get("original_url"):
            continue
        targets.append(i)

    total = len(targets)
    print(f"需要抓取說明：{total} 筆")
    if total == 0:
        print("所有條目已有說明，無需抓取。")
        return entries

    # 預估時間
    est_min = round(total * 2 / 60)
    print(f"預估時間：約 {est_min} 分鐘（每筆 ~2 秒）")

    saved_count = 0
    fail_count = 0

    for progress, i in enumerate(targets, 1):
        e = entries[i]
        url = e.get("original_url", "")
        name = e.get("campaign_name", "")[:35]

        if is_video_url(url):
            desc = fetch_video_description(url)
            source = "yt-dlp"
        else:
            desc = fetch_meta_description(url)
            source = "meta"
            time.sleep(0.5)  # 只有 meta 抓取需要 delay，yt-dlp 自帶 throttle

        if desc:
            entries[i]["description_en"] = desc
            saved_count += 1
            print(f"  [{progress}/{total}] ✓ [{source}] {name}")
            if progress <= 5 or progress % 20 == 0:
                print(f"    → {desc[:80]}...")
        else:
            entries[i]["description_en"] = ""
            fail_count += 1
            if progress % 50 == 0:
                print(f"  [{progress}/{total}] ✗ 無說明：{name}")

        # 斷點存檔
        if progress % SAVE_EVERY == 0:
            save_json(entries)
            print(f"  💾 存檔（{progress}/{total}，成功 {saved_count}，失敗 {fail_count}）")

    return entries


# ──────────────────────────────────────────────
# 主程式
# ──────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="作品說明抓取工具（yt-dlp + meta tag）")
    parser.add_argument("--gp-gold", action="store_true", help="只抓 Grand Prix + Gold")
    parser.add_argument("--year", type=int, help="只抓特定年份")
    args = parser.parse_args()

    if not DATA_PATH.exists():
        print(f"✗ 找不到資料檔：{DATA_PATH}")
        return

    print(f"讀取資料：{DATA_PATH}")
    with open(DATA_PATH, encoding="utf-8") as f:
        entries = json.load(f)

    entries = fetch_descriptions(
        entries,
        filter_gp_gold=args.gp_gold,
        filter_year=args.year,
    )

    save_json(entries)

    total_desc = sum(1 for e in entries if e.get("description_en"))
    print(f"\n完成！共 {total_desc} / {len(entries)} 筆有說明。")
    print(f"下一步：python scripts/translator.py --gp-gold")


if __name__ == "__main__":
    main()
