"""
Cannes Lions 得獎資料抓取工具
來源：lovetheworkmore.com
用法：
    python scraper.py --year 2024          # 抓取單一年份
    python scraper.py --all                # 抓 2015-2025 全部年份
    python scraper.py --all --upload       # 抓完後上傳到 Google Drive
"""

import argparse
import csv
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

BASE_DIR = Path(__file__).parent.parent
DATA_DIR = BASE_DIR / "docs" / "data"
SCRIPTS_DIR = Path(__file__).parent

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/121.0.0.0 Safari/537.36"
    )
}

YEAR_URL_CANDIDATES = {
    2025: ["https://lovetheworkmore.com/2025-2/"],
    2024: ["https://lovetheworkmore.com/2024-2/"],
    2023: ["https://lovetheworkmore.com/2023/", "https://lovetheworkmore.com/2023-2/"],
    2022: ["https://lovetheworkmore.com/2022/", "https://lovetheworkmore.com/2022-2/"],
    2021: ["https://lovetheworkmore.com/2021/", "https://lovetheworkmore.com/2021-2/"],
    2020: ["https://lovetheworkmore.com/2020/", "https://lovetheworkmore.com/2020-2/"],
    2019: ["https://lovetheworkmore.com/2019/", "https://lovetheworkmore.com/2019-2/"],
    2018: ["https://lovetheworkmore.com/2018/", "https://lovetheworkmore.com/2018-2/"],
    2017: ["https://lovetheworkmore.com/2017/", "https://lovetheworkmore.com/2017-2/"],
    2016: ["https://lovetheworkmore.com/2016-2/", "https://lovetheworkmore.com/2016/"],
    2015: ["https://lovetheworkmore.com/2015/", "https://lovetheworkmore.com/2015-2/"],
}

AWARD_LEVEL_KEYWORDS = ["GRAND PRIX", "TITANIUM", "GOLD", "SILVER", "BRONZE", "SHORTLIST"]
VIDEO_DOMAINS = ["youtube.com", "youtu.be", "vimeo.com"]

# ──────────────────────────────────────────────
# 正規表達式
# ──────────────────────────────────────────────

# 有 [CATEGORY] 前綴：[Film Lions] Campaign Name – Brand (Agency City)
ENTRY_WITH_CAT = re.compile(
    r"^\[([^\]]+)\]\s+(.+?)\s+[–—]\s+(.+?)\s*\((.+?)\)\s*$",
    re.UNICODE,
)

# 沒有 [CATEGORY]：Campaign Name – Brand (Agency City)
ENTRY_NO_CAT = re.compile(
    r"^(.+?)\s+[–—]\s+(.+?)\s*\((.+?)\)\s*$",
    re.UNICODE,
)

# 偵測完整行中的 [CATEGORY] 前綴（類別文字在 <a> 標籤外部）
# 例：[FILM] Campaign Name – Brand (Agency City)
ENTRY_CAT_PREFIX = re.compile(r"^\[([^\]]+)\]\s+(.+)$", re.UNICODE)

# ──────────────────────────────────────────────
# 工具函式
# ──────────────────────────────────────────────

def find_year_url(year: int) -> str | None:
    for url in YEAR_URL_CANDIDATES.get(year, []):
        try:
            r = requests.head(url, headers=HEADERS, timeout=10, allow_redirects=True)
            if r.status_code == 200:
                print(f"  ✓ {year} → {url}")
                return url
        except Exception:
            pass
    print(f"  ✗ {year} → 找不到可用 URL")
    return None


def detect_award_level(text: str) -> str | None:
    t = text.strip().upper()
    for kw in AWARD_LEVEL_KEYWORDS:
        if t == kw or t.startswith(kw + " ") or t.startswith(kw + "/"):
            return kw.title().replace(" Prix", " Prix")
    return None


def classify_media_type(url: str) -> str:
    if not url:
        return "其他"
    for d in VIDEO_DOMAINS:
        if d in url.lower():
            return "影片"
    ext = url.lower().split("?")[0].rsplit(".", 1)[-1]
    if ext in ("jpg", "jpeg", "png", "gif", "webp", "svg"):
        return "圖片"
    return "其他"


def parse_agency_city(raw: str) -> tuple[str, str]:
    """從 'WIEDEN+KENNEDY PORTLAND' 拆出 agency 和 city（最後全大寫單字）"""
    raw = raw.strip()
    parts = raw.rsplit(" ", 1)
    if len(parts) == 2 and len(parts[1]) > 1 and parts[1].replace("+", "").isalpha():
        return parts[0].strip().title(), parts[1].strip().title()
    return raw.title(), ""


def parse_entry(text: str, href: str, award_level: str, year: int) -> dict | None:
    """解析一個 <a> 標籤的文字成資料 dict"""
    text = text.strip()
    if not text or len(text) < 5:
        return None

    # 嘗試有 [CATEGORY] 的格式
    m = ENTRY_WITH_CAT.match(text)
    if m:
        cat_raw, campaign, brand, agency_raw = m.group(1), m.group(2), m.group(3), m.group(4)
        cats = [c.strip().title() for c in cat_raw.split("+")]
        agency, city = parse_agency_city(agency_raw)
        return _make_entry(year, award_level, cats[0], ", ".join(cats),
                           campaign, brand, agency, city, href)

    # 嘗試沒有 [CATEGORY] 的格式
    m2 = ENTRY_NO_CAT.match(text)
    if m2:
        campaign, brand, agency_raw = m2.group(1), m2.group(2), m2.group(3)
        # 過濾掉誤判（太短或是導航連結）
        if len(campaign) < 2 or len(brand) < 2:
            return None
        agency, city = parse_agency_city(agency_raw)
        return _make_entry(year, award_level, "", "", campaign, brand, agency, city, href)

    return None


def _make_entry(year, award_level, cat, all_cats, campaign, brand, agency, city, href):
    return {
        "year": year,
        "award_level": award_level,
        "cannes_category": cat,
        "all_categories": all_cats,
        "campaign_name": campaign.strip().title(),
        "brand": brand.strip().title(),
        "agency": agency,
        "city": city,
        "country": "",
        "media_type": classify_media_type(href),
        "original_url": href,
        "drive_path": "",
        "status": "正常" if href else "無連結",
    }

# ──────────────────────────────────────────────
# 主要抓取函式
# ──────────────────────────────────────────────

def scrape_year(year: int) -> list[dict]:
    url = find_year_url(year)
    if not url:
        return []

    print(f"  抓取頁面中...")
    try:
        resp = requests.get(url, headers=HEADERS, timeout=30)
        resp.raise_for_status()
    except Exception as e:
        print(f"  ✗ 抓取失敗：{e}")
        return []

    soup = BeautifulSoup(resp.text, "lxml")

    content_area = (
        soup.find("div", class_=re.compile(r"entry-content|post-content|et_pb_text"))
        or soup.find("article")
        or soup.body
    )

    if not content_area:
        print("  ✗ 找不到內容區域")
        return []

    # ── Step 1：從全文建立「行 → 獎項等級」及「連結文字 → 類別」對應表 ──
    # 頁面結構：
    #   GRAND PRIX / GOLD / SILVER / BRONZE 是純文字標題
    #   [FILM] Campaign – Brand (Agency) ← [CATEGORY] 在 <a> 標籤外部，<a> 只含後半段
    full_lines = [l.strip() for l in content_area.get_text(separator="\n").split("\n") if l.strip()]

    award_by_line: dict[str, str] = {}
    category_by_link_text: dict[str, str] = {}   # <a> 文字 → 坎城類別
    current_award = "Unknown"
    for line in full_lines:
        level = detect_award_level(line)
        if level:
            current_award = level
            print(f"    → 進入等級：{current_award}")
        else:
            # 偵測 [CATEGORY] 前綴行，例：[FILM] The Misheard Version – Specsavers (Golin London)
            cat_m = ENTRY_CAT_PREFIX.match(line)
            if cat_m:
                cat_raw  = cat_m.group(1).strip()
                link_txt = cat_m.group(2).strip()
                cats     = [c.strip().title() for c in cat_raw.split("+")]
                category_by_link_text[link_txt] = cats[0]
            if line not in award_by_line:
                award_by_line[line] = current_award

    # ── Step 2：找所有 <a> 標籤並解析 ──
    entries = []
    failed = []
    seen = set()

    for a in content_area.find_all("a", href=True):
        text = a.get_text(strip=True)
        href = a["href"]
        key = (text, href)
        if not text or key in seen:
            continue
        seen.add(key)

        award_level = award_by_line.get(text, current_award)
        entry = parse_entry(text, href, award_level, year)
        if entry:
            # [CATEGORY] 在 <a> 外部時，parse_entry 無法取得類別 → 這裡補上
            if not entry.get("cannes_category") and text in category_by_link_text:
                entry["cannes_category"] = category_by_link_text[text]
            entries.append(entry)
        elif ("–" in text or "—" in text) and len(text) > 10:
            failed.append({"raw_text": text, "year": year})

    print(f"  ✓ 解析完成：{len(entries)} 筆，失敗 {len(failed)} 筆")

    if failed:
        fail_path = DATA_DIR / f"parse_failed_{year}.json"
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        with open(fail_path, "w", encoding="utf-8") as f:
            json.dump(failed, f, ensure_ascii=False, indent=2)
        print(f"  ℹ 失敗條目存至 {fail_path.name}")

    return entries

# ──────────────────────────────────────────────
# Google Drive 上傳（可選）
# ──────────────────────────────────────────────

def get_drive_service():
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    SCOPES = ["https://www.googleapis.com/auth/drive"]
    creds_path = SCRIPTS_DIR / "credentials.json"
    token_path = SCRIPTS_DIR / "token.json"

    creds = None
    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not creds_path.exists():
                print("✗ 找不到 scripts/credentials.json")
                return None
            flow = InstalledAppFlow.from_client_secrets_file(str(creds_path), SCOPES)
            creds = flow.run_local_server(port=0)
        with open(token_path, "w") as f:
            f.write(creds.to_json())

    return build("drive", "v3", credentials=creds)


def get_or_create_folder(service, name: str, parent_id: str | None = None) -> str:
    q = f"name='{name}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
    if parent_id:
        q += f" and '{parent_id}' in parents"
    res = service.files().list(q=q, fields="files(id)").execute()
    files = res.get("files", [])
    if files:
        return files[0]["id"]
    meta = {"name": name, "mimeType": "application/vnd.google-apps.folder"}
    if parent_id:
        meta["parents"] = [parent_id]
    return service.files().create(body=meta, fields="id").execute()["id"]


def upload_file(service, local_path: Path, folder_id: str) -> str:
    from googleapiclient.http import MediaFileUpload
    name = local_path.name
    media = MediaFileUpload(str(local_path), mimetype="application/json", resumable=True)
    q = f"name='{name}' and '{folder_id}' in parents and trashed=false"
    res = service.files().list(q=q, fields="files(id)").execute()
    existing = res.get("files", [])
    if existing:
        fid = existing[0]["id"]
        service.files().update(fileId=fid, media_body=media).execute()
    else:
        meta = {"name": name, "parents": [folder_id]}
        fid = service.files().create(body=meta, media_body=media, fields="id").execute()["id"]
    return f"https://drive.google.com/file/d/{fid}/view"

# ──────────────────────────────────────────────
# 輸出
# ──────────────────────────────────────────────

def save_data(all_data: list[dict]):
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    json_path = DATA_DIR / "cannes_winners.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(all_data, f, ensure_ascii=False, indent=2)
    print(f"\n✓ JSON 已存：{json_path} （{len(all_data)} 筆）")

    csv_path = DATA_DIR / "cannes_winners.csv"
    if all_data:
        fieldnames = list(all_data[0].keys())
        with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(all_data)
        print(f"✓ CSV 已存：{csv_path}")

# ──────────────────────────────────────────────
# 主程式
# ──────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Cannes Lions 得獎資料抓取工具")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--year", type=int)
    group.add_argument("--all", action="store_true")
    parser.add_argument("--upload", action="store_true", help="抓完後上傳到 Google Drive")
    args = parser.parse_args()

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    years = [args.year] if args.year else list(range(2015, 2026))
    all_data = []

    drive_service = root_folder_id = None
    if args.upload:
        print("正在連線 Google Drive...")
        drive_service = get_drive_service()
        if drive_service:
            root_folder_id = get_or_create_folder(drive_service, "cannes")
            print(f"✓ Drive 連線成功")

    for year in years:
        print(f"\n[{year}] 開始抓取...")
        data = scrape_year(year)
        all_data.extend(data)

        if data and drive_service and root_folder_id:
            year_folder_id = get_or_create_folder(drive_service, str(year), root_folder_id)
            tmp = DATA_DIR / f"cannes_{year}.json"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            link = upload_file(drive_service, tmp, year_folder_id)
            print(f"  ✓ {year} 上傳至 Drive → {link}")

        if args.all:
            time.sleep(2)

    save_data(all_data)

    if drive_service and root_folder_id and all_data:
        data_folder_id = get_or_create_folder(drive_service, "data", root_folder_id)
        j = upload_file(drive_service, DATA_DIR / "cannes_winners.json", data_folder_id)
        c = upload_file(drive_service, DATA_DIR / "cannes_winners.csv", data_folder_id)
        print(f"\n✓ 合併 JSON 上傳 → {j}")
        print(f"✓ 合併 CSV 上傳 → {c}")

    print(f"\n完成！共 {len(all_data)} 筆得獎紀錄。")


if __name__ == "__main__":
    main()
