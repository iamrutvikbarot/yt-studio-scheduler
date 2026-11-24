import os
import sys
import json
import time
import subprocess
import tempfile
import datetime
from dateutil import parser
import requests
import gdown
import gspread
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

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


# ==============================================================================
# 1. FILE DOWNLOAD HELPER (GOOGLE DRIVE & DIRECT LINKS)
# ==============================================================================
def download_media(url, output_path):
    if not url or not str(url).strip():
        return None

    clean_url = str(url).strip()
    print(f"📥 Downloading: {clean_url} -> {output_path}")

    if "drive.google.com" in clean_url:
        try:
            gdown.download(clean_url, output_path, quiet=False, fuzzy=True)
            if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
                return output_path
        except Exception as e:
            print(f"⚠️ gdown failed, attempting direct download: {e}")

    response = requests.get(clean_url, stream=True, timeout=120)
    response.raise_for_status()
    with open(output_path, "wb") as f:
        for chunk in response.iter_content(chunk_size=1024 * 1024):
            if chunk:
                f.write(chunk)

    if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
        return output_path
    raise RuntimeError(f"Failed to download media from {url}")


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

def merge_audio_and_video(video_path, audio_path, output_path, music_volume=0.25):
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
            "-i", audio_path,
            "-map", "0:v",
            "-map", "1:a",
            "-c:v", "copy",
            "-c:a", "aac",
            "-b:a", "192k",
            "-shortest",
            output_path
        ]

    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"FFmpeg failed: {res.stderr}")

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

    init_url = f"https://graph.facebook.com/v19.0/{IG_USER_ID}/video_reels"
    init_resp = requests.post(init_url, data={
        "upload_phase": "start",
        "access_token": IG_ACCESS_TOKEN
    }).json()

    if "video_id" not in init_resp:
        raise RuntimeError(f"Instagram init failed: {init_resp}")

    video_id = init_resp["video_id"]
    upload_url = init_resp["upload_url"]

    print(f"🚀 Uploading video bytes to Instagram Reel (ID: {video_id})...")
    with open(video_path, "rb") as f:
        headers = {
            "Authorization": f"OAuth {IG_ACCESS_TOKEN}",
            "offset": "0",
            "file_size": str(file_size)
        }
        up_resp = requests.post(upload_url, headers=headers, data=f)
        up_resp.raise_for_status()

    finish_params = {
        "upload_phase": "finish",
        "access_token": IG_ACCESS_TOKEN,
        "video_id": video_id,
        "caption": full_caption
    }

    if target_utc_dt:
        seconds_ahead = (target_utc_dt - now_utc).total_seconds()
        if 600 <= seconds_ahead <= (75 * 86400):
            finish_params["scheduled_publish_time"] = int(target_utc_dt.timestamp())
            print(f"📅 Instagram Reel scheduled for: {int(target_utc_dt.timestamp())}")

    finish_resp = requests.post(init_url, data=finish_params).json()
    if not finish_resp.get("success"):
        raise RuntimeError(f"Instagram finish failed: {finish_resp}")

    print(f"✅ Instagram Reel registered successfully! Media ID: {video_id}")
    return video_id


# ==============================================================================
# 5. FACEBOOK PAGE REELS UPLOADER & SCHEDULER
# ==============================================================================
def resolve_facebook_page_token():
    if FB_PAGE_ACCESS_TOKEN:
        return FB_PAGE_ACCESS_TOKEN
    if FB_PAGE_ID and IG_ACCESS_TOKEN:
        url = f"https://graph.facebook.com/v19.0/{FB_PAGE_ID}?fields=access_token&access_token={IG_ACCESS_TOKEN}"
        res = requests.get(url).json()
        if "access_token" in res:
            return res["access_token"]
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

    print(f"✅ Facebook Page Reel registered successfully! Video ID: {video_id}")
    return video_id


# ==============================================================================
# 6. SMART GOOGLE SHEET TAB & COLUMN RESOLUTION
# ==============================================================================
def find_target_worksheet(spreadsheet):
    """
    Finds the correct worksheet. Prioritizes tabs named like 'Shorts & Reels Auto Scheduler'
    or tabs that contain relevant headers.
    """
    all_ws = spreadsheet.worksheets()
    print(f"📑 Available Worksheets: {[ws.title for ws in all_ws]}")

    # 1. Match by name
    for ws in all_ws:
        t = ws.title.lower()
        if "short" in t or "reel" in t or "scheduler" in t or "auto" in t:
            print(f"🎯 Selected Worksheet by Name: '{ws.title}'")
            return ws

    # 2. Match by content
    for ws in all_ws:
        rows = ws.get_all_values()
        for r in rows[:5]:
            combined = " ".join([str(c).lower().strip() for c in r])
            if "ig_caption" in combined or "yt_title" in combined or "status" in combined:
                print(f"🎯 Selected Worksheet by Content: '{ws.title}'")
                return ws

    # 3. Fallback to first sheet
    print(f"⚠️ Falling back to first sheet: '{spreadsheet.sheet1.title}'")
    return spreadsheet.sheet1

def get_field(row_dict, *candidate_keys, default=""):
    """Fetches first matching non-empty key from candidate list."""
    for k in candidate_keys:
        k_clean = k.lower().strip()
        if k_clean in row_dict and str(row_dict[k_clean]).strip():
            return str(row_dict[k_clean]).strip()
    return default

def find_col_idx(headers, *candidate_names, default=1):
    """Finds 1-based column index matching any candidate name."""
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

    # Automatically select the right tab!
    sheet = find_target_worksheet(spreadsheet)

    all_rows = sheet.get_all_values()
    if not all_rows or len(all_rows) < 1:
        print(f"📊 Worksheet '{sheet.title}' is completely empty.")
        return

    # Find header row in top 5 rows
    header_row_index = 0
    found_headers = False
    for r_idx, r in enumerate(all_rows[:5]):
        combined = " ".join([str(c).lower().strip() for c in r])
        if "status" in combined or "ig_caption" in combined or "video_url" in combined or "yt_title" in combined:
            header_row_index = r_idx
            found_headers = True
            break

    raw_headers = all_rows[header_row_index]
    headers = [str(h).strip().lower() for h in raw_headers]
    print(f"📊 Detected Headers on '{sheet.title}' (Row {header_row_index + 1}): {headers}")

    data_rows = all_rows[header_row_index + 1:]
    if not data_rows:
        print(f"📊 No data rows below the header row on '{sheet.title}'.")
        return

    # Dynamic column mapping
    c_status = find_col_idx(headers, "status", default=2)
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
        if status != "PENDING":
            continue

        title = get_field(row_dict, "yt_title", "title", "video_title", default="Untitled Short")
        print(f"\n=======================================================")
        print(f"🎯 Processing Row #{i}: '{title}'")
        print(f"=======================================================")

        # Mark as PROCESSING
        sheet.update_cell(i, c_status, "PROCESSING")

        with tempfile.TemporaryDirectory() as tmp_dir:
            try:
                video_url = get_field(row_dict, "video_url", "video url", "video link", "video_link", "video")
                music_url = get_field(row_dict, "music_url", "music url", "audio_url", "music", "song")
                music_vol = float(get_field(row_dict, "music_volume", "music volume", "volume", default="0.25"))

                # Date & Time resolution (supports separate date + time columns or combined scheduled_time)
                scheduled_str = get_field(row_dict, "scheduled_time", "scheduled time")
                if not scheduled_str:
                    s_date = get_field(row_dict, "schedule date", "schedule_date", "date")
                    s_time = get_field(row_dict, "schedule time", "schedule_time", "time")
                    if s_date and s_time:
                        scheduled_str = f"{s_date} {s_time}".strip()
                    elif s_date:
                        scheduled_str = s_date.strip()

                target_utc = parse_target_time(scheduled_str)

                # 1. Download raw video
                raw_video_path = os.path.join(tmp_dir, "raw_video.mp4")
                download_media(video_url, raw_video_path)

                # 2. Download and merge music (if provided)
                final_video_path = raw_video_path
                if music_url and str(music_url).strip():
                    raw_audio_path = os.path.join(tmp_dir, "raw_music.mp3")
                    download_media(music_url, raw_audio_path)

                    mixed_video_path = os.path.join(tmp_dir, "mixed_video.mp4")
                    final_video_path = merge_audio_and_video(
                        raw_video_path, raw_audio_path, mixed_video_path, music_vol
                    )

                # 3. Upload to YouTube Shorts
                yt_id = None
                try:
                    yt_id = upload_to_youtube(
                        video_path=final_video_path,
                        title=title,
                        description=get_field(row_dict, "yt_description", "description", "desc"),
                        tags=get_field(row_dict, "yt_tags", "tags"),
                        target_utc_dt=target_utc
                    )
                except Exception as ex_yt:
                    print(f"❌ YouTube Upload Failed: {ex_yt}")

                # 4. Upload to Instagram Reels
                ig_id = None
                try:
                    ig_id = upload_to_instagram(
                        video_path=final_video_path,
                        caption=get_field(row_dict, "ig_caption", "caption"),
                        hashtags=get_field(row_dict, "ig_hashtags", "hashtags"),
                        target_utc_dt=target_utc
                    )
                except Exception as ex_ig:
                    print(f"❌ Instagram Upload Failed: {ex_ig}")

                # 5. Upload to Facebook Page Reels
                fb_id = None
                try:
                    fb_id = upload_to_facebook_page(
                        video_path=final_video_path,
                        caption=get_field(row_dict, "ig_caption", "caption"),
                        hashtags=get_field(row_dict, "ig_hashtags", "hashtags"),
                        target_utc_dt=target_utc
                    )
                except Exception as ex_fb:
                    print(f"❌ Facebook Upload Failed: {ex_fb}")

                # 6. Update Sheet
                yt_link = f"https://youtu.be/{yt_id}" if yt_id else ""
                new_status = "SCHEDULED" if target_utc else "PUBLISHED"

                sheet.update_cell(i, c_status, new_status)
                if yt_link:
                    sheet.update_cell(i, c_yt_link, yt_link)
                if ig_id:
                    sheet.update_cell(i, c_ig_id, str(ig_id))
                if fb_id:
                    sheet.update_cell(i, c_fb_id, str(fb_id))
                sheet.update_cell(i, c_log, f"Success at {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
                print(f"🎉 Row #{i} successfully processed for YT, IG, and FB!")

            except Exception as e:
                err_msg = str(e)
                print(f"❌ Critical Error processing Row #{i}: {err_msg}")
                sheet.update_cell(i, c_status, "FAILED")
                sheet.update_cell(i, c_log, f"Error: {err_msg[:200]}")

    print("\n🏁 All pending items finished.")

if __name__ == "__main__":
    process_sheet()
