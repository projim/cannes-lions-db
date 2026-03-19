"""
作品說明翻譯工具（googletrans — 完全免費，不需要 API key）

用法：
    python scripts/translator.py             # 翻譯全部
    python scripts/translator.py --gp-gold   # 只翻 Grand Prix + Gold
    python scripts/translator.py --year 2024 # 只翻特定年份
"""

import argparse
import json
import time
from pathlib import Path

# ──────────────────────────────────────────────
# 設定
# ──────────────────────────────────────────────

BASE_DIR = Path(__file__).parent.parent
DATA_PATH = BASE_DIR / "docs" / "data" / "cannes_winners.json"

SAVE_EVERY = 50    # 每 N 筆存一次
REQUEST_DELAY = 1  # 秒（避免 rate limit）
MAX_RETRIES = 3

GP_GOLD_LEVELS = {"grand prix", "titanium", "gold"}

# ──────────────────────────────────────────────
# 翻譯
# ──────────────────────────────────────────────

def get_translator():
    """取得 googletrans Translator 實例（延遲 import）"""
    try:
        from googletrans import Translator
        return Translator()
    except ImportError:
        print("✗ 找不到 googletrans，請執行：pip install googletrans==4.0.0rc1 httpx==0.13.3")
        return None


def translate_text(translator, text: str, retries: int = MAX_RETRIES) -> str:
    """翻譯單筆文字，失敗自動 retry"""
    if not text:
        return ""

    # 截斷至 250 字元（節省翻譯量）
    text_to_translate = text[:250]

    for attempt in range(retries):
        try:
            result = translator.translate(text_to_translate, src="en", dest="zh-tw")
            if result and result.text:
                return result.text.strip()
        except Exception as e:
            if attempt < retries - 1:
                wait = (attempt + 1) * 2
                print(f"    ⚠ 翻譯失敗（第 {attempt+1} 次），{wait} 秒後重試：{e}")
                time.sleep(wait)
            else:
                print(f"    ✗ 翻譯失敗，放棄：{e}")
    return ""


def save_json(entries: list[dict]):
    with open(DATA_PATH, "w", encoding="utf-8") as f:
        json.dump(entries, f, ensure_ascii=False, indent=2)


# ──────────────────────────────────────────────
# 主程式
# ──────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="作品說明翻譯工具（googletrans）")
    parser.add_argument("--gp-gold", action="store_true", help="只翻 Grand Prix + Gold")
    parser.add_argument("--year", type=int, help="只翻特定年份")
    args = parser.parse_args()

    if not DATA_PATH.exists():
        print(f"✗ 找不到資料檔：{DATA_PATH}")
        print("  請先執行 scraper.py")
        return

    translator = get_translator()
    if not translator:
        return

    print(f"讀取資料：{DATA_PATH}")
    with open(DATA_PATH, encoding="utf-8") as f:
        entries = json.load(f)

    # 篩選待翻譯條目
    targets = []
    for i, e in enumerate(entries):
        if not e.get("description_en"):
            continue  # 沒有英文說明，跳過
        if e.get("description_zh"):
            continue  # 已有翻譯，跳過
        if args.year and e.get("year") != args.year:
            continue
        if args.gp_gold and e.get("award_level", "").lower() not in GP_GOLD_LEVELS:
            continue
        targets.append(i)

    total = len(targets)
    print(f"待翻譯：{total} 筆")

    if total == 0:
        print("所有條目已翻譯完畢，或沒有可翻譯的說明。")
        return

    translated_count = 0
    failed_count = 0

    for progress, i in enumerate(targets, 1):
        e = entries[i]
        name = e.get("campaign_name", "")[:30]
        text = e.get("description_en", "")

        zh = translate_text(translator, text)

        if zh:
            entries[i]["description_zh"] = zh
            translated_count += 1
            if progress % 5 == 0 or progress <= 3:
                print(f"  [{progress}/{total}] ✓ {name}")
                print(f"    EN: {text[:60]}...")
                print(f"    ZH: {zh[:60]}...")
        else:
            entries[i]["description_zh"] = ""
            failed_count += 1

        time.sleep(REQUEST_DELAY)

        # 斷點存檔
        if progress % SAVE_EVERY == 0:
            save_json(entries)
            print(f"  💾 存檔（{progress}/{total}，成功 {translated_count}，失敗 {failed_count}）")

    # 最後一次存檔
    save_json(entries)

    print(f"\n完成！")
    print(f"  成功翻譯：{translated_count} 筆")
    print(f"  翻譯失敗：{failed_count} 筆（description_zh 設為空字串，可重跑）")
    print(f"  已存至：{DATA_PATH}")


if __name__ == "__main__":
    main()
