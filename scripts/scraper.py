"""
Cannes Lions 得獎資料抓取工具
來源：lovetheworkmore.com
用法：
    python scraper.py --year 2024          # 抓單一年份
    python scraper.py --all                # 抓 2015-2025 全部年份
    python scraper.py --all --upload       # 抓完後上傳到 Google Drive
"""

import argparse
import csv
import json
import os
import re
import sys
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup

# ──────────────────────────────────────────────
# 設定
# ──────────────────────────────────────────────

BASE_DIR = Path(__file__).parent.parent
DATA_DIR = BASE_DIR / "data"
SCRIPTS_DIR = Path(__file__).parent

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/121.0.0.0 Safari/537.36"
    )
}

# 年份 URL 對照表（依網站實際結構）
YEAR_URL_CANDIDATES = {
    2025: ["https://lovetheworkmore.com/2025-2/"],
    2024: ["https://lovetheworkmore.com/2024-2/"],
    2023: [
        "https://lovetheworkmore.com/2023/",
        "https://lovetheworkmore.com/2023-2/",
    ],
    2022: [
        "https://lovetheworkmore.com/2022/",
        "https://lovetheworkmore.com/2022-2/",
    ],
    2021: [
        "https://lovetheworkmore.com/2021/",
        "https://lovetheworkmore.com/2021-2/",
    ],
    2020: [
        "https://lovetheworkmore.com/2020/",
        "https://lovetheworkmore.com/2020-2/",
    ],
    2019: [
        "https://lovetheworkmore.com/2019/",
        "https://lovetheworkmore.com/2019-2/",
    ],
    2018: [
        "https://lovetheworkmore.com/2018/",
        "https://lovetheworkmore.com/2018-2/",
    ],
    2017: [
        "https://lovetheworkmore.com/2017/",
        "https://lovetheworkmore.com/2017-2/",
    ],
    2016: [
        "https://lovetheworkmore.com/2016-2/",
        "https://lovetheworkmore.com/2016/",
    ],
    2015: [
        "https://lovetheworkmore.com/2015/",
        "https://lovetheworkmore.com/2015-2/",
    ],
}

AWARD_LEVEL_KEYWORDS = [
    "GRAND PRIX",
    "TITANIUM",
    "GOLD",
    "SILVER",
    "BRONZE",
    "SHORTLIST",
]

VIDEO_DOMAINS = ["youtube.com", "youtu.be", "vimeo.com"]


# ──────────────────────────────────────────────
# URL 探測
# ──────────────────────────────────────────────

def find_year_url(year: int) -> str | None:
    """試探年份的可用 URL"""
    candidates = YEAR_URL_CANDIDATES.get(year, [])
    for url in candidates:
        try:
            resp = requests.head(url, headers=HEADERS, timeout=10, allow_redirects=True)
            if resp.status_code == 200:
                print(f"  ✓ {year} → {url}")
                return url
        except Exception:
            pass
    print(f"  ✗ {year} → 找不到可用 URL")
    return None


# ──────────────────────────────────────────────
# 解析邏輯
# ──────────────────────────────────────────────

def detect_award_level(text: str) -> str | None:
    """判斷一段文字是否為獎項等級標題"""
    t = text.strip().upper()
    for kw in AWARD_LEVEL_KEYWORDS:
        if t == kw or t.startswith(kw + " "):
            return kw.title().replace("Prix", "Prix")
    return None


def classify_media_type(url: str) -> str:
    """根據 URL 判斷媒體類型"""
    if not url:
        return "其他"
    url_lower = url.lower()
    for domain in VIDEO_DOMAINS:
        if domain in url_lower:
            return "影片"
    ext = url_lower.split("?")[0].split(".")[-1]
    if ext in ("jpg", "jpeg", "png", "gif", "webp", "svg"):
        return "圖片"
    return "其他"


def parse_agency_city(raw: str) -> tuple[str, str]:
    """
    從 'WIEDEN+KENNEDY PORTLAND' 這類字串拆出 agency 和 city
    規則：最後一個「全大寫單字」視為 city，其餘為 agency
    """
    raw = raw.strip()
    parts = raw.rsplit(" ", 1)
    if len(parts) == 2 and parts[1].isupper() and len(parts[1]) > 1:
        return parts[0].strip().title(), parts[1].strip().title()
    return raw.title(), ""


# 條目解析正規表達式
# 格式：[CATEGORY] CAMPAIGN NAME – BRAND (AGENCY CITY)
ENTRY_PATTERN = re.compile(
    r"^\[([^\]]+)\]\s+"          # [CATEGORY]
    r"(.+?)"                      # CAMPAIGN NAME
    r"\s+[–—-]\s+"               # em-dash / en-dash
    r"(.+?)"                      # BRAND
    r"\s*\((.+?)\)\s*$",          # (AGENCY CITY)
    re.UNICODE,
)


def parse_entry_line(line: str, url: str, award_level: str, year: int) -> dict | None:
    """解析一行條目，回傳資料 dict 或 None"""
    line = line.strip()
    if not line:
        return None

    m = ENTRY_PATTERN.match(line)
    if not m:
        return None

    category_raw, campaign_raw, brand_raw, agency_raw = (
        m.group(1),
        m.group(2),
        m.group(3),
        m.group(4),
    )

    # 類別可能有多個，用 + 分隔，取第一個作為主類別
    categories = [c.strip().title() for c in category_raw.split("+")]
    cannes_category = categories[0]

    agency, city = parse_agency_city(agency_raw)

    return {
        "year": year,
        "award_level": award_level,
        "cannes_category": cannes_category,
        "all_categories": ", ".join(categories),
        "campaign_name": campaign_raw.strip().title(),
        "brand": brand_raw.strip().title(),
        "agency": agency,
        "city": city,
        "country": "",
        "media_type": classify_media_type(url),
        "original_url": url,
        "drive_path": "",
        "status": "正常" if url else "無連結",
    }


# ──────────────────────────────────────────────
# 主要抓取函式
# ──────────────────────────────────────────────

def scrape_year(year: int) -> list[dict]:
    """抓取單一年份的得獎資料"""
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

    # 抓取所有段落和連結，建立 (text, href) 配對清單
    # 策略：遍歷所有 <p> 和純文字節點，同時記錄同一段落內的 <a href>
    entries = []
    current_award_level = "Unknown"
    failed_lines = []

    # 取得頁面所有文字區塊（含連結資訊）
    # 找所有含文字的元素，排除導航/頁首/頁尾
    content_area = (
        soup.find("div", class_=re.compile(r"entry-content|post-content|et_pb_text"))
        or soup.find("article")
        or soup.body
    )

    if not content_area:
        print("  ✗ 找不到內容區域")
        return []

    # 遍歷所有文字節點
    for element in content_area.find_all(["p", "div", "h1", "h2", "h3", "h4", "li"]):
        # 跳過巢狀的 div（避免重複處理）
        if element.name == "div" and element.find(["p", "div"]):
            continue

        text = element.get_text(separator=" ", strip=True)
        if not text:
            continue

        # 檢查是否為獎項等級標題
        level = detect_award_level(text)
        if level:
            current_award_level = level
            print(f"    → 進入等級：{current_award_level}")
            continue

        # 找此元素內的連結
        links = element.find_all("a", href=True)
        href = links[0]["href"] if links else ""

        # 嘗試解析條目（元素可能含多行）
        for line in text.split("\n"):
            line = line.strip()
            if not line:
                continue

            # 跳過純標題行
            if detect_award_level(line):
                current_award_level = detect_award_level(line)
                continue

            entry = parse_entry_line(line, href, current_award_level, year)
            if entry:
                entries.append(entry)
            elif "[" in line and ("–" in line or "—" in line or "-" in line):
                # 看起來像條目但解析失敗，記錄下來
                failed_lines.append({"raw_text": line, "year": year})

    print(f"  ✓ 解析完成：{len(entries)} 筆，失敗 {len(failed_lines)} 筆")

    # 儲存解析失敗的條目供人工檢查
    if failed_lines:
        fail_path = DATA_DIR / f"parse_failed_{year}.json"
        with open(fail_path, "w", encoding="utf-8") as f:
            json.dump(failed_lines, f, ensure_ascii=False, indent=2)
        print(f"  ℹ 失敗條目已存至 {fail_path.name}")

    return entries


# ──────────────────────────────────────────────
# Google Drive 上傳（可選）
# ──────────────────────────────────────────────

def get_drive_service():
    """建立 Google Drive API 服務"""
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


def get_or_create_drive_folder(service, name: str, parent_id: str | None = None) -> str:
    """在 Drive 上取得或建立資料夾，回傳 folder ID"""
    query = f"name='{name}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
    if parent_id:
        query += f" and '{parent_id}' in parents"

    result = service.files().list(q=query, fields="files(id, name)").execute()
    files = result.get("files", [])

    if files:
        return files[0]["id"]

    # 建立新資料夾
    metadata = {
        "name": name,
        "mimeType": "application/vnd.google-apps.folder",
    }
    if parent_id:
        metadata["parents"] = [parent_id]

    folder = service.files().create(body=metadata, fields="id").execute()
    return folder["id"]


def upload_json_to_drive(service, local_path: Path, drive_folder_id: str) -> str:
    """上傳 JSON 檔案到 Drive，回傳 Drive 連結"""
    from googleapiclient.http import MediaFileUpload

    file_name = local_path.name
    media = MediaFileUpload(str(local_path), mimetype="application/json", resumable=True)

    # 檢查是否已存在同名檔案
    query = f"name='{file_name}' and '{drive_folder_id}' in parents and trashed=false"
    result = service.files().list(q=query, fields="files(id)").execute()
    existing = result.get("files", [])

    if existing:
        # 更新現有檔案
        file_id = existing[0]["id"]
        service.files().update(fileId=file_id, media_body=media).execute()
    else:
        # 新建檔案
        metadata = {"name": file_name, "parents": [drive_folder_id]}
        file = service.files().create(body=metadata, media_body=media, fields="id").execute()
        file_id = file["id"]

    return f"https://drive.google.com/file/d/{file_id}/view"


def upload_year_to_drive(service, year: int, data: list[dict], root_folder_id: str):
    """上傳單年資料到 Drive cannes/{year}/"""
    year_folder_id = get_or_create_drive_folder(service, str(year), root_folder_id)

    # 存到暫存 JSON 再上傳
    temp_path = DATA_DIR / f"cannes_{year}.json"
    with open(temp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    link = upload_json_to_drive(service, temp_path, year_folder_id)
    print(f"  ✓ {year} 資料已上傳 Drive → {link}")


def upload_all_to_drive(service, all_data: list[dict]):
    """上傳合併資料到 Drive cannes/data/"""
    root_folder_id = get_or_create_drive_folder(service, "cannes")
    data_folder_id = get_or_create_drive_folder(service, "data", root_folder_id)

    json_path = DATA_DIR / "cannes_winners.json"
    csv_path = DATA_DIR / "cannes_winners.csv"

    link_json = upload_json_to_drive(service, json_path, data_folder_id)
    link_csv = upload_json_to_drive(service, csv_path, data_folder_id)
    print(f"  ✓ 合併 JSON 已上傳 → {link_json}")
    print(f"  ✓ 合併 CSV 已上傳 → {link_csv}")


# ──────────────────────────────────────────────
# 輸出
# ──────────────────────────────────────────────

def save_data(all_data: list[dict]):
    """儲存 JSON 和 CSV"""
    DATA_DIR.mkdir(exist_ok=True)

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
    group.add_argument("--year", type=int, help="抓取單一年份（例：2024）")
    group.add_argument("--all", action="store_true", help="抓取 2015–2025 全部年份")
    parser.add_argument("--upload", action="store_true", help="抓完後上傳到 Google Drive")
    args = parser.parse_args()

    DATA_DIR.mkdir(exist_ok=True)

    years = [args.year] if args.year else list(range(2015, 2026))
    all_data = []

    drive_service = None
    root_folder_id = None
    if args.upload:
        print("正在連線 Google Drive...")
        drive_service = get_drive_service()
        if drive_service:
            root_folder_id = get_or_create_drive_folder(drive_service, "cannes")
            print(f"✓ Drive 連線成功，cannes/ 資料夾 ID：{root_folder_id}")
        else:
            print("✗ Drive 連線失敗，將跳過上傳")

    for year in years:
        print(f"\n[{year}] 開始抓取...")
        data = scrape_year(year)
        all_data.extend(data)

        if data and drive_service and root_folder_id:
            upload_year_to_drive(drive_service, year, data, root_folder_id)

        if args.all:
            time.sleep(2)  # 避免對伺服器造成負擔

    save_data(all_data)

    if drive_service and root_folder_id and all_data:
        print("\n正在上傳合併資料到 Drive...")
        upload_all_to_drive(drive_service, all_data)

    print(f"\n完成！共 {len(all_data)} 筆得獎紀錄。")


if __name__ == "__main__":
    main()
