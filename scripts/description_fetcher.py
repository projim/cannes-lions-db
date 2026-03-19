"""
作品說明抓取工具 v3 — 統一用 og:description / meta description

策略：所有 URL（YouTube / Vimeo / 其他）統一直接抓頁面的 og:description
- YouTube og:description 包含影片說明的前幾行
- Vimeo / DandAD / Contagious 等也都有 og:description
- 不需要任何 API 金鑰，不依賴可能被封鎖的第三方服務

用法：
    python scripts/description_fetcher.py             # 抓全部
    python scripts/description_fetcher.py --gp-gold   # 只抓 Grand Prix + Gold
    python scripts/description_fetcher.py --year 2024 # 只抓特定年份
    python scripts/description_fetcher.py --test 5    # 測試前 N 筆（看結果用）
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

BASE_DIR  = Path(__file__).parent.parent
DATA_PATH = BASE_DIR / "docs" / "data" / "cannes_winners.json"

# 模擬真實瀏覽器，增加成功率
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

REQUEST_DELAY = 0.5   # 秒
SAVE_EVERY    = 50
GP_GOLD_LEVELS = {"grand prix", "titanium", "gold"}


# ──────────────────────────────────────────────
# 說明抓取（統一邏輯）
# ──────────────────────────────────────────────

def fetch_description(url: str) -> str:
    """
    抓取任意頁面的 og:description 或 meta description。
    YouTube / Vimeo / 其他頁面全部走這個函式。
    """
    if not url or url.startswith("mailto") or url.startswith("#"):
        return ""

    try:
        resp = requests.get(
            url,
            headers=HEADERS,
            timeout=12,
            allow_redirects=True,
        )
        if resp.status_code != 200:
            return ""

        soup = BeautifulSoup(resp.text, "lxml")

        # 1. og:description（大多數平台都有，包含 YouTube 影片說明前幾行）
        og = soup.find("meta", property="og:description")
        if og and og.get("content", "").strip():
            return og["content"].strip()[:500]

        # 2. name="description"（一般 HTML meta）
        meta = soup.find("meta", attrs={"name": "description"})
        if meta and meta.get("content", "").strip():
            return meta["content"].strip()[:500]

    except requests.exceptions.Timeout:
        pass
    except Exception:
        pass

    return ""


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
        test_n: int | None) -> list[dict]:

    targets = [
        i for i, e in enumerate(entries)
        if not e.get("description_en")          # 空字串 "" 也會被包含（允許重試）
        and e.get("original_url")
        and (not filter_gp_gold or e.get("award_level", "").lower() in GP_GOLD_LEVELS)
        and (not filter_year   or e.get("year") == filter_year)
    ]

    if test_n:
        targets = targets[:test_n]

    total = len(targets)
    print(f"待抓取：{total} 筆")
    if not total:
        print("全部已完成，無需重抓。")
        return entries

    est = round(total * (REQUEST_DELAY + 0.5) / 60)
    print(f"預估時間：約 {max(1, est)} 分鐘")

    ok = fail = 0

    for progress, i in enumerate(targets, 1):
        e    = entries[i]
        url  = e["original_url"]
        name = e.get("campaign_name", "")[:35]

        desc = fetch_description(url)
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
            pct = round(ok / progress * 100)
            print(f"  💾 [{progress}/{total}] 存檔 — 成功率 {pct}%（✓{ok} ✗{fail}）")

    return entries


# ──────────────────────────────────────────────
# 主程式
# ──────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="作品說明抓取工具（og:description）")
    parser.add_argument("--gp-gold", action="store_true", help="只抓 Grand Prix + Gold")
    parser.add_argument("--year",    type=int,            help="只抓特定年份")
    parser.add_argument("--test",    type=int, metavar="N", help="只抓前 N 筆（測試用）")
    args = parser.parse_args()

    if not DATA_PATH.exists():
        print(f"✗ 找不到 {DATA_PATH}，請先執行 scraper.py")
        return

    with open(DATA_PATH, encoding="utf-8") as f:
        entries = json.load(f)
    print(f"讀取 {len(entries)} 筆資料")

    entries = run(entries,
                  filter_gp_gold=args.gp_gold,
                  filter_year=args.year,
                  test_n=args.test)
    save(entries)

    have = sum(1 for e in entries if e.get("description_en"))
    pct  = round(have / len(entries) * 100)
    print(f"\n完成！{have} / {len(entries)} 筆有說明（{pct}%）")

    if have > 0:
        print("下一步：python scripts/translator.py --gp-gold")


if __name__ == "__main__":
    main()
