import os
import sys
import re
import json
import time
import random
import html
import subprocess
import tempfile
import datetime
from dateutil import parser
import requests
import gdown
import gspread
from google.oauth2.credentials import Credentials
from google.oauth2 import service_account
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload

# ==============================================================================
# CONFIGURATION & ENVIRONMENT VARIABLES
# ==============================================================================
SHEET_ID = os.getenv("GOOGLE_SHEET_ID")
SERVICE_ACCOUNT_JSON = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")

# YouTube OAuth
YT_CLIENT_ID = os.getenv("YT_CLIENT_ID")
YT_CLIENT_SECRET = os.getenv("YT_CLIENT_SECRET")
YT_REFRESH_TOKEN = os.getenv("YT_REFRESH_TOKEN")

# Instagram Meta Graph API
IG_USER_ID = os.getenv("IG_USER_ID")
IG_ACCESS_TOKEN = os.getenv("IG_ACCESS_TOKEN")

# Facebook Page Graph API
FB_PAGE_ID = os.getenv("FB_PAGE_ID")
FB_PAGE_ACCESS_TOKEN = os.getenv("FB_PAGE_ACCESS_TOKEN")

# Default Timezone offset (IST +05:30 by default)
TZ_OFFSET_HOURS = float(os.getenv("TIMEZONE_OFFSET_HOURS", "5.5"))

# Default Google Drive Music Folder URL (used when row's music_url is empty)
DEFAULT_MUSIC_FOLDER_URL = os.getenv(
    "DEFAULT_MUSIC_FOLDER_URL",
    "https://drive.google.com/drive/folders/1_dtklc3nCicJc1WRj5DUeHMSlQX9LvSF"
)


# ==============================================================================
# 1. FILE DOWNLOAD HELPER (BULLETPROOF GOOGLE DRIVE & DIRECT LINKS)
# ==============================================================================
AUDIO_EXTENSIONS = (".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac", ".opus")


def extract_gdrive_folder_id(url):
    if not url:
        return None
    m = re.search(r'/folders/([a-zA-Z0-9_-]+)', url)
    if m:
        return m.group(1)
    m = re.search(r'folderview\?[^#]*\bid=([a-zA-Z0-9_-]+)', url)
    if m:
        return m.group(1)
    return None


def extract_gdrive_id(url):
    if extract_gdrive_folder_id(url):
        return None
    m = re.search(r'/file/d/([a-zA-Z0-9_-]+)', url)
    if m:
        return m.group(1)
    m = re.search(r'[?&]id=([a-zA-Z0-9_-]+)', url)
    if m:
        return m.group(1)
    m = re.search(r'/d/([a-zA-Z0-9_-]+)', url)
    if m:
        return m.group(1)
    return None


def get_drive_service(sa_info):
    if not sa_info:
        return None
    creds = service_account.Credentials.from_service_account_info(
        sa_info,
        scopes=["https://www.googleapis.com/auth/drive.readonly"]
    )
    return build("drive", "v3", credentials=creds)


def _is_audio_entry(name, mime_type=""):
    mime = (mime_type or "").lower()
    lower_name = (name or "").lower().strip()
    if mime.startswith("audio/"):
        return True
    return lower_name.endswith(AUDIO_EXTENSIONS)


def list_gdrive_folder_audio_files(folder_id, sa_info=None):
    audio_files = []

    # Strategy A: Official Google Drive v3 API via Service Account
    if sa_info:
        try:
            drive = get_drive_service(sa_info)
            page_token = None
            all_items = []
            while True:
                resp = drive.files().list(
                    q=f"'{folder_id}' in parents and trashed = false",
                    fields="nextPageToken, files(id, name, mimeType)",
                    pageSize=1000,
                    pageToken=page_token,
                    supportsAllDrives=True,
                    includeItemsFromAllDrives=True
                ).execute()
                all_items.extend(resp.get("files", []))
                page_token = resp.get("nextPageToken")
                if not page_token:
                    break

            for item in all_items:
                mime = item.get("mimeType", "")
                if mime == "application/vnd.google-apps.folder":
                    continue
                if _is_audio_entry(item.get("name", ""), mime):
                    audio_files.append({"id": item["id"], "name": item.get("name", item["id"])})

            if audio_files:
                print(f"  🎵 Found {len(audio_files)} audio file(s) in Drive folder via API.")
                return audio_files
            elif all_items:
                print(f"  ⚠️ Drive folder has {len(all_items)} file(s), but none matched audio formats {AUDIO_EXTENSIONS}.")
        except Exception as e:
            print(f"  ⚠️ Drive API folder listing failed: {e}")

    # Strategy B: Public Drive embeddedfolderview fallback (works if folder is 'Anyone with the link')
    try:
        embed_url = f"https://drive.google.com/embeddedfolderview?id={folder_id}#list"
        resp = requests.get(
            embed_url,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
            timeout=30
        )
        if resp.status_code == 200:
            entries = re.findall(
                r'href="https://drive\.google\.com/file/d/([a-zA-Z0-9_-]+)[^"]*"[^>]*>.*?<div class="flip-entry-title">([^<]+)</div>',
                resp.text,
                re.DOTALL
            )
            seen = set()
            for fid, raw_name in entries:
                if fid in seen:
                    continue
                seen.add(fid)
                clean_name = html.unescape(raw_name).strip()
                if _is_audio_entry(clean_name):
                    audio_files.append({"id": fid, "name": clean_name})

            if not audio_files:
                # Fallback in case titles are hidden or audio files have no extension
                raw_ids = re.findall(r'/file/d/([a-zA-Z0-9_-]+)', resp.text)
                for fid in dict.fromkeys(raw_ids):
                    audio_files.append({"id": fid, "name": f"{fid}.mp3"})

            if audio_files:
                print(f"  🎵 Found {len(audio_files)} audio file(s) in public Drive folder.")
                return audio_files
    except Exception as e:
        print(f"  ⚠️ Public folder listing fallback failed: {e}")

    raise RuntimeError(
        f"No audio files found in Google Drive folder '{folder_id}'. "
        f"Ensure the folder contains audio files (.mp3/.wav/.m4a) and sharing is set to "
        f"'Anyone with the link can view' (or shared with your Service Account email)."
    )


def resolve_music_url(music_url, sa_info=None):
    if not music_url or not str(music_url).strip():
        return None, None, False

    clean_url = str(music_url).strip()
    folder_id = extract_gdrive_folder_id(clean_url)
    if not folder_id:
        return clean_url, None, False

    print(f"📂 Detected Google Drive music folder ID: {folder_id}. Picking a random song...")
    audio_files = list_gdrive_folder_audio_files(folder_id, sa_info=sa_info)
    chosen = random.choice(audio_files)
    chosen_url = f"https://drive.google.com/file/d/{chosen['id']}/view?usp=drive_link"
    print(f"  🎲 Randomly picked song: '{chosen['name']}' ({chosen_url})")
    return chosen_url, chosen["name"], True

def is_valid_media_file(file_path):
    if not os.path.exists(file_path) or os.path.getsize(file_path) < 1024:
        return False
    try:
        with open(file_path, "rb") as f:
            head = f.read(1024).lower()
        if b"<!doctype html" in head or b"<html" in head or b"<head" in head or b"<title" in head:
            return False
        return True
    except Exception:
        return False

def download_media(url, output_path, sa_info=None):
    if not url or not str(url).strip():
        return None

    clean_url = str(url).strip()
    print(f"📥 Downloading: {clean_url} -> {output_path}")

    file_id = extract_gdrive_id(clean_url)
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    })

    if file_id:
        print(f"  🔍 Detected Google Drive File ID: {file_id}")

        # Strategy 1: Google Drive UserContent CDN (direct stream, bypasses virus scan confirmation & bot scrapers)
        try:
            cdn_url = f"https://drive.usercontent.google.com/download?id={file_id}&export=download&confirm=t"
            resp = session.get(cdn_url, stream=True, timeout=120)
            if resp.status_code == 200 and "text/html" not in resp.headers.get("content-type", "").lower():
                with open(output_path, "wb") as f:
                    for chunk in resp.iter_content(chunk_size=1024 * 1024):
                        if chunk:
                            f.write(chunk)
                if is_valid_media_file(output_path):
                    print(f"  ✅ Successfully downloaded {os.path.getsize(output_path)} bytes via Google Drive Direct CDN.")
                    return output_path
        except Exception as e:
            print(f"  ⚠️ Strategy 1 (Drive UserContent CDN) failed: {e}")

        # Strategy 2: docs.google.com/uc with session cookie confirm
        try:
            uc_url = "https://docs.google.com/uc?export=download"
            resp = session.get(uc_url, params={"id": file_id}, stream=True, timeout=120)
            token = None
            for key, val in session.cookies.items():
                if key.startswith("download_warning"):
                    token = val
                    break
            if token:
                resp = session.get(uc_url, params={"id": file_id, "confirm": token}, stream=True, timeout=120)

            if resp.status_code == 200 and "text/html" not in resp.headers.get("content-type", "").lower():
                with open(output_path, "wb") as f:
                    for chunk in resp.iter_content(chunk_size=1024 * 1024):
                        if chunk:
                            f.write(chunk)
                if is_valid_media_file(output_path):
                    print(f"  ✅ Successfully downloaded {os.path.getsize(output_path)} bytes via Google Docs UC.")
                    return output_path
        except Exception as e:
            print(f"  ⚠️ Strategy 2 (Google Docs UC) failed: {e}")

        # Strategy 3: gdown by ID
        try:
            gdown.download(id=file_id, output=output_path, quiet=False)
            if is_valid_media_file(output_path):
                print(f"  ✅ Downloaded {os.path.getsize(output_path)} bytes from Google Drive via gdown.")
                return output_path
        except Exception as e:
            print(f"  ⚠️ Strategy 3 (gdown) failed: {e}")

        # Strategy 3b: Authenticated Google Drive API download (if shared with Service Account)
        if sa_info:
            try:
                drive = get_drive_service(sa_info)
                request = drive.files().get_media(fileId=file_id, supportsAllDrives=True)
                with open(output_path, "wb") as f:
                    downloader = MediaIoBaseDownload(f, request)
                    done = False
                    while not done:
                        _, done = downloader.next_chunk()
                if is_valid_media_file(output_path):
                    print(f"  ✅ Downloaded {os.path.getsize(output_path)} bytes via Google Drive API.")
                    return output_path
            except Exception as e:
                print(f"  ⚠️ Strategy 3b (Drive API download) failed: {e}")

    # Strategy 4: Standard Direct HTTP/HTTPS Download (for non-Google Drive URLs)
    if not file_id:
        try:
            response = session.get(clean_url, stream=True, timeout=120)
            response.raise_for_status()
            with open(output_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if chunk:
                        f.write(chunk)
            if is_valid_media_file(output_path):
                print(f"  ✅ Successfully downloaded {os.path.getsize(output_path)} bytes from direct URL.")
                return output_path
        except Exception as e:
            print(f"  ⚠️ Strategy 4 (direct URL download) failed: {e}")

    # Clean up and report descriptive error if HTML was downloaded
    if os.path.exists(output_path):
        is_html = False
        try:
            with open(output_path, "rb") as f:
                sample = f.read(512).lower()
            if b"<html" in sample or b"<!doctype" in sample:
                is_html = True
            os.remove(output_path)
        except Exception:
            pass
        if is_html:
            raise RuntimeError(
                f"Google Drive returned an HTML page instead of video/audio file. "
                f"Please ensure the file sharing is set to 'Anyone with the link can view' (Viewer)."
            )

    raise RuntimeError(f"Failed to download valid media from URL: {url}")


# ==============================================================================
# 2. AUDIO MIXING & FFmpeg ENGINE
# ==============================================================================
def has_audio_stream(video_path):
    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "a",
        "-show_entries", "stream=codec_type",
        "-of", "csv=p=0",
        video_path
    ]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return "audio" in res.stdout.lower()
    except Exception:
        return False

def merge_audio_and_video(video_path, audio_path, output_path, music_volume=1.0):
    if not audio_path or not os.path.exists(audio_path):
        return video_path

    print(f"🎬 Merging audio into video (Music Volume: {music_volume})...")
    video_has_audio = has_audio_stream(video_path)

    if video_has_audio:
        filter_str = (
            f"[0:a]volume=1.0[v_voice];"
            f"[1:a]volume={music_volume}[v_music];"
            f"[v_voice][v_music]amix=inputs=2:duration=first[a_out]"
        )
        cmd = [
            "ffmpeg", "-y",
            "-i", video_path,
            "-stream_loop", "-1",
            "-i", audio_path,
            "-filter_complex", filter_str,
            "-map", "0:v",
            "-map", "[a_out]",
            "-c:v", "copy",
            "-c:a", "aac",
            "-b:a", "192k",
            "-shortest",
            output_path
        ]
    else:
        cmd = [
            "ffmpeg", "-y",
            "-i", video_path,
            "-stream_loop", "-1",
            "-i", audio_path,
            "-map", "0:v",
            "-map", "1:a",
            "-c:v", "copy",
            "-c:a", "aac",
            "-af", f"volume={music_volume}",
            "-b:a", "192k",
            "-shortest",
            output_path
        ]

    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        err_lines = [line.strip() for line in res.stderr.strip().splitlines() if line.strip()]
        short_err = " | ".join(err_lines[-4:]) if err_lines else "Unknown FFmpeg error"
        raise RuntimeError(f"FFmpeg failed: {short_err}")

    return output_path


# ==============================================================================
# 3. YOUTUBE SHORTS UPLOADER & SCHEDULER
# ==============================================================================
def get_youtube_client():
    creds = Credentials(
        token=None,
        refresh_token=YT_REFRESH_TOKEN,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=YT_CLIENT_ID,
        client_secret=YT_CLIENT_SECRET,
        scopes=["https://www.googleapis.com/auth/youtube.upload"]
    )
    creds.refresh(Request())
    return build("youtube", "v3", credentials=creds)

def upload_to_youtube(video_path, title, description, tags, target_utc_dt=None):
    if not YT_REFRESH_TOKEN or not YT_CLIENT_ID:
        print("⚠️ YouTube credentials not set. Skipping YouTube upload.")
        return None

    youtube = get_youtube_client()
    now_utc = datetime.datetime.now(datetime.timezone.utc)

    tag_list = [t.strip() for t in str(tags).split(",") if t.strip()]
    full_description = f"{description}\n\n#Shorts"

    body = {
        "snippet": {
            "title": str(title)[:100],
            "description": full_description,
            "tags": tag_list,
            "categoryId": "22"
        },
        "status": {
            "selfDeclaredMadeForKids": False
        }
    }

    if target_utc_dt and (target_utc_dt - now_utc).total_seconds() > 300:
        body["status"]["privacyStatus"] = "private"
        body["status"]["publishAt"] = target_utc_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        print(f"📅 YouTube Short scheduled for: {body['status']['publishAt']}")
    else:
        body["status"]["privacyStatus"] = "public"
        print("📢 YouTube Short scheduled for immediate public release.")

    media = MediaFileUpload(video_path, chunksize=-1, resumable=True, mimetype="video/mp4")
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)

    print(f"🚀 Uploading to YouTube: '{title}'...")
    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            print(f"  YouTube upload progress: {int(status.progress() * 100)}%")

    video_id = response.get("id")
    print(f"✅ YouTube Upload Complete! Link: https://youtu.be/{video_id}")
    return video_id


# ==============================================================================
# 4. INSTAGRAM REELS UPLOADER & SCHEDULER
# ==============================================================================
def upload_to_instagram(video_path, caption, hashtags, target_utc_dt=None):
    if not IG_USER_ID or not IG_ACCESS_TOKEN:
        print("⚠️ Instagram credentials not set. Skipping Instagram upload.")
        return None

    full_caption = f"{caption}\n\n{hashtags}".strip()
    file_size = os.path.getsize(video_path)
    now_utc = datetime.datetime.now(datetime.timezone.utc)

    init_url = f"https://graph.facebook.com/v19.0/{IG_USER_ID}/media"
    init_data = {
        "media_type": "REELS",
        "upload_type": "resumable",
        "caption": full_caption,
        "access_token": IG_ACCESS_TOKEN
    }

    print(f"🚀 Initializing Instagram Reels Container on /{IG_USER_ID}/media...")
    init_resp = requests.post(init_url, data=init_data).json()
    if "id" not in init_resp or "uri" not in init_resp:
        raise RuntimeError(f"Instagram container init failed: {init_resp}")

    container_id = init_resp["id"]
    upload_url = init_resp["uri"]

    print(f"🚀 Uploading video bytes to Instagram Reel (Container ID: {container_id})...")
    with open(video_path, "rb") as f:
        headers = {
            "Authorization": f"OAuth {IG_ACCESS_TOKEN}",
            "offset": "0",
            "file_size": str(file_size)
        }
        up_resp = requests.post(upload_url, headers=headers, data=f)
        up_resp.raise_for_status()

    print("⏳ Waiting for Instagram Reel container to finish processing...")
    status_url = f"https://graph.facebook.com/v19.0/{container_id}?fields=status_code,status&access_token={IG_ACCESS_TOKEN}"
    for attempt in range(20):
        time.sleep(5)
        st_resp = requests.get(status_url).json()
        st_code = st_resp.get("status_code")
        print(f"  Container status: {st_code}")
        if st_code == "FINISHED":
            break
        elif st_code == "ERROR":
            raise RuntimeError(f"Instagram container processing failed: {st_resp}")

    print("📢 Publishing Instagram Reel...")
    pub_url = f"https://graph.facebook.com/v19.0/{IG_USER_ID}/media_publish"
    pub_resp = requests.post(pub_url, data={
        "creation_id": container_id,
        "access_token": IG_ACCESS_TOKEN
    }).json()
    if "id" in pub_resp:
        media_id = pub_resp["id"]
        # Fetch direct permalink
        perm_url = f"https://graph.facebook.com/v19.0/{media_id}?fields=permalink&access_token={IG_ACCESS_TOKEN}"
        perm_resp = requests.get(perm_url).json()
        final_link = perm_resp.get("permalink") or f"https://www.instagram.com/reel/{media_id}/"
        print(f"✅ Instagram Reel Published! Link: {final_link}")
        return final_link
    else:
        raise RuntimeError(f"Instagram publish failed: {pub_resp}")


# ==============================================================================
# 5. FACEBOOK PAGE REELS UPLOADER & SCHEDULER
# ==============================================================================
def resolve_facebook_page_token():
    if FB_PAGE_ACCESS_TOKEN:
        if FB_PAGE_ID:
            try:
                check = requests.get(
                    f"https://graph.facebook.com/v19.0/{FB_PAGE_ID}?fields=id&access_token={FB_PAGE_ACCESS_TOKEN}",
                    timeout=15
                ).json()
                if "error" not in check:
                    return FB_PAGE_ACCESS_TOKEN
                print(f"  ⚠️ FB_PAGE_ACCESS_TOKEN invalid/expired ({check['error'].get('message', '')}). Trying IG_ACCESS_TOKEN fallback...")
            except Exception:
                return FB_PAGE_ACCESS_TOKEN
        else:
            return FB_PAGE_ACCESS_TOKEN
    if FB_PAGE_ID and IG_ACCESS_TOKEN:
        url = f"https://graph.facebook.com/v19.0/{FB_PAGE_ID}?fields=access_token&access_token={IG_ACCESS_TOKEN}"
        res = requests.get(url, timeout=15).json()
        if "access_token" in res:
            return res["access_token"]
        if "error" in res:
            print(f"  ⚠️ Could not derive Page Token from IG_ACCESS_TOKEN: {res['error'].get('message', res['error'])}")
    return None

def upload_to_facebook_page(video_path, caption, hashtags, target_utc_dt=None):
    if not FB_PAGE_ID:
        print("⚠️ FB_PAGE_ID not set. Skipping Facebook Page upload.")
        return None

    fb_token = resolve_facebook_page_token()
    if not fb_token:
        print("⚠️ Could not resolve Facebook Page Token. Skipping Facebook upload.")
        return None

    full_caption = f"{caption}\n\n{hashtags}".strip()
    file_size = os.path.getsize(video_path)
    now_utc = datetime.datetime.now(datetime.timezone.utc)

    init_url = f"https://graph.facebook.com/v19.0/{FB_PAGE_ID}/video_reels"
    init_resp = requests.post(init_url, data={
        "upload_phase": "start",
        "access_token": fb_token
    }).json()

    if "video_id" not in init_resp:
        raise RuntimeError(f"Facebook Page Reel init failed: {init_resp}")

    video_id = init_resp["video_id"]
    upload_url = init_resp["upload_url"]

    print(f"🚀 Uploading video bytes to Facebook Page Reel (ID: {video_id})...")
    with open(video_path, "rb") as f:
        headers = {
            "Authorization": f"OAuth {fb_token}",
            "offset": "0",
            "file_size": str(file_size)
        }
        up_resp = requests.post(upload_url, headers=headers, data=f)
        up_resp.raise_for_status()

    finish_params = {
        "upload_phase": "finish",
        "access_token": fb_token,
        "video_id": video_id,
        "description": full_caption
    }

    if target_utc_dt:
        seconds_ahead = (target_utc_dt - now_utc).total_seconds()
        if 600 <= seconds_ahead <= (75 * 86400):
            finish_params["video_state"] = "SCHEDULED"
            finish_params["scheduled_publish_time"] = int(target_utc_dt.timestamp())
            print(f"📅 Facebook Page Reel scheduled for: {int(target_utc_dt.timestamp())}")
        else:
            finish_params["video_state"] = "PUBLISHED"
    else:
        finish_params["video_state"] = "PUBLISHED"

    finish_resp = requests.post(init_url, data=finish_params).json()
    if not finish_resp.get("success"):
        raise RuntimeError(f"Facebook Page Reel finish failed: {finish_resp}")

    reel_link = f"https://www.facebook.com/reel/{video_id}"
    print(f"✅ Facebook Page Reel registered! Link: {reel_link}")
    return reel_link


# ==============================================================================
# 6. SMART GOOGLE SHEET RESOLUTION & PROCESSING
# ==============================================================================
def find_target_worksheet(spreadsheet):
    all_ws = spreadsheet.worksheets()
    print(f"📑 Available Worksheets: {[ws.title for ws in all_ws]}")

    for ws in all_ws:
        t = ws.title.lower()
        if "short" in t or "reel" in t or "scheduler" in t or "auto" in t:
            print(f"🎯 Selected Worksheet by Name: '{ws.title}'")
            return ws

    for ws in all_ws:
        rows = ws.get_all_values()
        for r in rows[:5]:
            combined = " ".join([str(c).lower().strip() for c in r])
            if "ig_caption" in combined or "yt_title" in combined or "status" in combined:
                print(f"🎯 Selected Worksheet by Content: '{ws.title}'")
                return ws

    return spreadsheet.sheet1

def get_field(row_dict, *candidate_keys, default=""):
    for k in candidate_keys:
        k_clean = k.lower().strip()
        if k_clean in row_dict and str(row_dict[k_clean]).strip():
            return str(row_dict[k_clean]).strip()
    return default

def find_col_idx(headers, *candidate_names, default=1):
    for name in candidate_names:
        clean = name.lower().strip()
        if clean in headers:
            return headers.index(clean) + 1
    return default

def parse_target_time(time_str):
    if not time_str or str(time_str).strip().upper() in ["", "NOW", "IMMEDIATE"]:
        return None
    try:
        dt = parser.parse(str(time_str))
        if dt.tzinfo is None:
            tz = datetime.timezone(datetime.timedelta(hours=TZ_OFFSET_HOURS))
            dt = dt.replace(tzinfo=tz)
        return dt.astimezone(datetime.timezone.utc)
    except Exception as e:
        print(f"⚠️ Failed to parse datetime '{time_str}': {e}. Defaulting to NOW.")
        return None

def process_sheet():
    if not SHEET_ID or not SERVICE_ACCOUNT_JSON:
        print("❌ Error: Missing GOOGLE_SHEET_ID or GOOGLE_SERVICE_ACCOUNT_JSON!")
        sys.exit(1)

    sa_info = json.loads(SERVICE_ACCOUNT_JSON)
    gc = gspread.service_account_from_dict(sa_info)
    spreadsheet = gc.open_by_key(SHEET_ID)

    sheet = find_target_worksheet(spreadsheet)

    all_rows = sheet.get_all_values()
    if not all_rows or len(all_rows) < 1:
        print(f"📊 Worksheet '{sheet.title}' is completely empty.")
        return

    header_row_index = 0
    for r_idx, r in enumerate(all_rows[:5]):
        combined = " ".join([str(c).lower().strip() for c in r])
        if "status" in combined or "ig_caption" in combined or "video_url" in combined or "yt_title" in combined:
            header_row_index = r_idx
            break

    raw_headers = all_rows[header_row_index]
    headers = [str(h).strip().lower() for h in raw_headers]
    print(f"📊 Detected Headers on '{sheet.title}' (Row {header_row_index + 1}): {headers}")

    data_rows = all_rows[header_row_index + 1:]
    if not data_rows:
        print(f"📊 No data rows below header row on '{sheet.title}'.")
        return

    c_status = find_col_idx(headers, "status", default=2)
    c_music_url = find_col_idx(headers, "music_url", "music url", "audio_url", "music", "song", default=0)
    c_yt_link = find_col_idx(headers, "yt_link", "yt link", "youtube link", default=12)
    c_ig_id = find_col_idx(headers, "ig_id", "ig id", "instagram id", default=13)
    c_fb_id = find_col_idx(headers, "fb_id", "fb id", "facebook id", default=14)
    c_log = find_col_idx(headers, "log", "logs", "error", default=15)

    for i, row in enumerate(data_rows, start=header_row_index + 2):
        row_dict = {}
        for idx, col_name in enumerate(headers):
            if col_name:
                row_dict[col_name] = row[idx] if idx < len(row) else ""

        status = get_field(row_dict, "status").upper()
        title = get_field(row_dict, "yt_title", "title", "video_title", default=f"Row #{i}")

        # Parse schedule date and time
        scheduled_str = get_field(row_dict, "scheduled_time", "scheduled time")
        if not scheduled_str:
            s_date = get_field(row_dict, "schedule date", "schedule_date", "date")
            s_time = get_field(row_dict, "schedule time", "schedule_time", "time")
            if s_date and s_time:
                scheduled_str = f"{s_date} {s_time}".strip()
            elif s_date:
                scheduled_str = s_date.strip()

        target_utc = parse_target_time(scheduled_str)
        now_utc = datetime.datetime.now(datetime.timezone.utc)

        existing_yt_link = get_field(row_dict, "yt_link", "yt link", "youtube link")
        existing_fb_id = get_field(row_dict, "fb_id", "fb id", "facebook id")
        existing_ig_id = get_field(row_dict, "ig_id", "ig id", "instagram id")
        ig_is_live = existing_ig_id.startswith("http")

        # Determine if we should process this row
        should_process = False
        is_scheduled_trigger = False

        if status in ["PENDING", "RETRY"]:
            should_process = True
        elif status == "SCHEDULED" and not ig_is_live:
            if not target_utc or now_utc >= target_utc:
                should_process = True
                is_scheduled_trigger = True
                print(f"  ⏰ Scheduled time arrived for Row #{i} ('{title[:25]}...')! Publishing pending Instagram Reel...")
            else:
                mins_left = int((target_utc - now_utc).total_seconds() / 60)
                print(f"  ⏳ Row #{i} ('{title[:25]}...'): Status='SCHEDULED' ({mins_left} mins until {scheduled_str}). Waiting for scheduled time.")
                continue
        else:
            print(f"  📋 Row #{i} ('{title[:25]}...'): Status='{status}'. Skipping.")
            continue

        if not should_process:
            continue

        print(f"\n=======================================================")
        if is_scheduled_trigger:
            print(f"🚀 Cloud-Schedule Triggered for Row #{i}: '{title}'")
        else:
            print(f"🎯 Processing Row #{i}: '{title}'")
        print(f"=======================================================")

        sheet.update_cell(i, c_status, "PROCESSING")

        with tempfile.TemporaryDirectory() as tmp_dir:
            try:
                video_url = get_field(row_dict, "video_url", "video url", "video link", "video_link", "video")
                if not video_url or not str(video_url).strip():
                    raise RuntimeError("Missing video URL! Column 'video_url' (Column D) is empty. Please provide a Google Drive video link.")

                music_url = get_field(row_dict, "music_url", "music url", "audio_url", "music", "song")
                if not music_url or not str(music_url).strip():
                    music_url = DEFAULT_MUSIC_FOLDER_URL
                    print(f"  🎵 'music_url' is empty — using default music folder: {music_url}")
                music_vol = 1.0

                # 1. Download raw video via Google Drive ID
                raw_video_path = os.path.join(tmp_dir, "raw_video.mp4")
                download_media(video_url, raw_video_path, sa_info=sa_info)

                if not os.path.exists(raw_video_path) or os.path.getsize(raw_video_path) < 1024:
                    raise RuntimeError(f"Video file was not downloaded properly from '{video_url}'")

                # 2. Download and merge music (if provided — supports single file or Drive folder)
                final_video_path = raw_video_path
                picked_song_name = None
                picked_song_url = None
                was_random_from_folder = False

                if music_url and str(music_url).strip():
                    resolved_music_url, picked_song_name, was_random_from_folder = resolve_music_url(
                        music_url, sa_info=sa_info
                    )
                    if resolved_music_url:
                        picked_song_url = resolved_music_url
                        ext = ".mp3"
                        if picked_song_name and "." in picked_song_name:
                            candidate_ext = os.path.splitext(picked_song_name)[1].lower()
                            if candidate_ext in AUDIO_EXTENSIONS:
                                ext = candidate_ext
                        raw_audio_path = os.path.join(tmp_dir, f"raw_music{ext}")
                        download_media(resolved_music_url, raw_audio_path, sa_info=sa_info)

                        mixed_video_path = os.path.join(tmp_dir, "mixed_video.mp4")
                        final_video_path = merge_audio_and_video(
                            raw_video_path, raw_audio_path, mixed_video_path, music_vol
                        )

                # 3. Upload to YouTube Shorts (Skip if already uploaded)
                yt_link = existing_yt_link
                if not yt_link or not yt_link.startswith("http"):
                    try:
                        yt_id = upload_to_youtube(
                            video_path=final_video_path,
                            title=title,
                            description=get_field(row_dict, "yt_description", "description", "desc"),
                            tags=get_field(row_dict, "yt_tags", "tags"),
                            target_utc_dt=target_utc
                        )
                        if yt_id:
                            yt_link = f"https://youtu.be/{yt_id}"
                    except Exception as ex_yt:
                        print(f"❌ YouTube Upload Failed: {ex_yt}")
                else:
                    print(f"  ℹ️ YouTube Short already uploaded: {existing_yt_link}. Skipping YT upload.")

                # 4. Upload to Facebook Page Reels (Skip if already uploaded)
                fb_link = existing_fb_id
                fb_error = None
                if not fb_link or not fb_link.startswith("http"):
                    try:
                        fb_link = upload_to_facebook_page(
                            video_path=final_video_path,
                            caption=get_field(row_dict, "ig_caption", "caption"),
                            hashtags=get_field(row_dict, "ig_hashtags", "hashtags"),
                            target_utc_dt=target_utc
                        )
                    except Exception as ex_fb:
                        fb_error = str(ex_fb)
                        print(f"❌ Facebook Upload Failed: {ex_fb}")
                else:
                    print(f"  ℹ️ Facebook Page Reel already uploaded: {existing_fb_id}. Skipping FB upload.")

                # 5. Upload to Instagram Reels
                ig_link = existing_ig_id
                is_future = bool(target_utc and (target_utc - now_utc).total_seconds() > 600)

                if not ig_link or not ig_link.startswith("http"):
                    if is_future:
                        ig_link = f"⏳ Scheduled for {scheduled_str}"
                        print(f"  ⏳ Instagram Reel queued. Will automatically publish at {scheduled_str}.")
                    else:
                        try:
                            ig_link = upload_to_instagram(
                                video_path=final_video_path,
                                caption=get_field(row_dict, "ig_caption", "caption"),
                                hashtags=get_field(row_dict, "ig_hashtags", "hashtags")
                            )
                        except Exception as ex_ig:
                            print(f"❌ Instagram Upload Failed: {ex_ig}")
                else:
                    print(f"  ℹ️ Instagram Reel already live: {existing_ig_id}. Skipping IG upload.")

                # 6. Update Sheet
                fb_status_note = "FB" if (fb_link and str(fb_link).startswith("http")) else ("FB FAILED" if fb_error else "FB skipped")
                if is_future:
                    new_status = "SCHEDULED"
                    log_text = f"YT & {fb_status_note} | IG queued for {scheduled_str}"
                else:
                    new_status = "PUBLISHED"
                    log_text = f"YT & {fb_status_note} & IG processed at {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
                if fb_error:
                    log_text += f" | FB Err: {fb_error[:100]}"

                if was_random_from_folder and picked_song_name:
                    log_text += f" | Music: {picked_song_name}"
                    if c_music_url > 0 and picked_song_url:
                        sheet.update_cell(i, c_music_url, picked_song_url)

                sheet.update_cell(i, c_status, new_status)
                if yt_link:
                    sheet.update_cell(i, c_yt_link, yt_link)
                if ig_link:
                    sheet.update_cell(i, c_ig_id, str(ig_link))
                if fb_link:
                    sheet.update_cell(i, c_fb_id, str(fb_link))
                sheet.update_cell(i, c_log, log_text)
                print(f"🎉 Row #{i} successfully processed: Status={new_status} | YT={yt_link} | IG={ig_link} | FB={fb_link}")

            except Exception as e:
                err_msg = str(e)
                print(f"❌ Critical Error processing Row #{i}: {err_msg}")
                sheet.update_cell(i, c_status, "FAILED")
                sheet.update_cell(i, c_log, f"Error: {err_msg[:200]}")

    print("\n🏁 All pending items finished.")

if __name__ == "__main__":
    process_sheet()
