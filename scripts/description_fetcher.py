"""
作品說明抓取工具（無需任何 API 金鑰）

- YouTube → Invidious API（YouTube 開源前端，繞過 bot detection）
- Vimeo   → Vimeo oEmbed API（免費公開）
- 其他    → 頁面 og:description meta 標籤

用法：
    python scripts/description_fetcher.py             # 抓全部
    python scripts/description_fetcher.py --gp-gold   # 只抓 Grand Prix + Gold
    python scripts/description_fetcher.py --year 2024 # 只抓特定年份
"""

import argparse
import json
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
        "Chrome/121.0.0.0 Safari/537.36"
    )
}

# Invidious 公開 instance 清單（依序嘗試）
INVIDIOUS_INSTANCES = [
    "https://inv.nadeko.net",
    "https://invidious.fdn.fr",
    "https://yt.artemislena.eu",
    "https://invidious.lunar.icu",
]

SAVE_EVERY   = 50
META_DELAY   = 0.8   # 非影片頁面的請求間隔（秒）
GP_GOLD_LEVELS = {"grand prix", "titanium", "gold"}


# ──────────────────────────────────────────────
# YouTube（Invidious API）
# ──────────────────────────────────────────────

def extract_youtube_id(url: str) -> str | None:
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


def fetch_youtube_via_invidious(video_id: str) -> str:
    """用 Invidious API 抓 YouTube 影片說明，自動換備用 instance"""
    for instance in INVIDIOUS_INSTANCES:
        try:
            r = requests.get(
                f"{instance}/api/v1/videos/{video_id}",
                timeout=10,
                headers=HEADERS,
            )
            if r.status_code == 200:
                data = r.json()
                desc = (data.get("description") or "").strip()
                if desc:
                    return desc[:500]
        except Exception:
            continue  # 換下一個 instance
    return ""


# ──────────────────────────────────────────────
# Vimeo（oEmbed API）
# ──────────────────────────────────────────────

def fetch_vimeo_description(url: str) -> str:
    """用 Vimeo oEmbed API 抓說明（不需要帳號）"""
    try:
        r = requests.get(
            "https://vimeo.com/api/oembed.json",
            params={"url": url},
            timeout=10,
            headers=HEADERS,
        )
        if r.status_code == 200:
            desc = (r.json().get("description") or "").strip()
            return desc[:500]
    except Exception:
        pass
    return ""


# ──────────────────────────────────────────────
# 其他 URL（og:description / meta description）
# ──────────────────────────────────────────────

def fetch_meta_description(url: str) -> str:
    if not url or url.startswith("mailto"):
        return ""
    try:
        r = requests.get(url, headers=HEADERS, timeout=10, allow_redirects=True)
        if r.status_code != 200:
            return ""
        soup = BeautifulSoup(r.text, "lxml")

        og = soup.find("meta", property="og:description")
        if og and og.get("content"):
            return og["content"].strip()[:500]

        meta = soup.find("meta", attrs={"name": "description"})
        if meta and meta.get("content"):
            return meta["content"].strip()[:500]
    except Exception:
        pass
    return ""


# ──────────────────────────────────────────────
# 主要抓取邏輯
# ──────────────────────────────────────────────

def fetch_descriptions(entries: list[dict],
                       filter_gp_gold: bool = False,
                       filter_year: int | None = None) -> list[dict]:

    targets = [
        i for i, e in enumerate(entries)
        if not e.get("description_en")
        and e.get("original_url")
        and (not filter_gp_gold or e.get("award_level", "").lower() in GP_GOLD_LEVELS)
        and (not filter_year   or e.get("year") == filter_year)
    ]

    total = len(targets)
    print(f"待抓取：{total} 筆（已有說明的跳過）")
    if not targets:
        print("全部已完成。")
        return entries

    est = round(total * 1.5 / 60)
    print(f"預估時間：約 {est} 分鐘")

    ok = fail = 0

    for progress, i in enumerate(targets, 1):
        e   = entries[i]
        url = e["original_url"]
        name = e.get("campaign_name", "")[:35]

        # ── 判斷來源 ──
        vid_id = extract_youtube_id(url)
        if vid_id:
            desc   = fetch_youtube_via_invidious(vid_id)
            source = "Invidious"
        elif "vimeo.com" in url.lower():
            desc   = fetch_vimeo_description(url)
            source = "Vimeo"
        else:
            desc   = fetch_meta_description(url)
            source = "meta"
            time.sleep(META_DELAY)

        if desc:
            entries[i]["description_en"] = desc
            ok += 1
            # 前 3 筆和每 25 筆印一次預覽
            if progress <= 3 or progress % 25 == 0:
                print(f"  [{progress}/{total}] ✓ [{source}] {name}")
                print(f"    {desc[:80]}...")
        else:
            entries[i]["description_en"] = ""
            fail += 1

        # 斷點存檔
        if progress % SAVE_EVERY == 0:
            _save(entries)
            print(f"  💾 [{progress}/{total}] 存檔（✓{ok} ✗{fail}）")

    return entries


def _save(entries: list[dict]):
    with open(DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(entries, f, ensure_ascii=False, indent=2)


# ──────────────────────────────────────────────
# 主程式
# ──────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--gp-gold", action="store_true", help="只抓 Grand Prix + Gold")
    parser.add_argument("--year",    type=int,            help="只抓特定年份")
    args = parser.parse_args()

    if not DATA_PATH.exists():
        print(f"✗ 找不到 {DATA_PATH}，請先執行 scraper.py")
        return

    with open(DATA_PATH, encoding="utf-8") as f:
        entries = json.load(f)
    print(f"讀取 {len(entries)} 筆資料")

    entries = fetch_descriptions(entries,
                                 filter_gp_gold=args.gp_gold,
                                 filter_year=args.year)
    _save(entries)

    have = sum(1 for e in entries if e.get("description_en"))
    print(f"\n完成！{have} / {len(entries)} 筆有說明")
    print("下一步：python scripts/translator.py --gp-gold")


if __name__ == "__main__":
    main()
