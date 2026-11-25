# 🚀 Complete Setup Guide: 100% Free YouTube, Instagram & Facebook Cloud Auto-Publisher

This system uploads and schedules your short videos automatically 24x7 across **three platforms**:
1. **YouTube Shorts**
2. **Instagram Reels**
3. **Facebook Page Reels**

GitHub Actions combines your video and background music (via FFmpeg) and schedules the upload to all three platforms using official, free APIs.

---

## 📋 1. Google Sheet Setup

Create a new Google Sheet and set up the following **15 columns** in Row 1:

| Col # | Column Header | Description / Example |
| :--- | :--- | :--- |
| **A** | `id` | Unique ID (e.g. `1`, `2`, `3`) |
| **B** | `status` | Set to `PENDING` when ready to publish. Script updates to `SCHEDULED` or `FAILED`. |
| **C** | `scheduled_time` | Format: `YYYY-MM-DD HH:MM` (e.g., `2026-11-25 18:30`) or `NOW` |
| **D** | `video_url` | Google Drive link or direct URL to the video file |
| **E** | `music_url` | *(Optional)* Google Drive link to an audio file **or a Google Drive folder** (picks a random audio file automatically), or direct URL. If left empty, uses the default music folder. |
| **F** | `music_volume` | *(Optional)* Background music volume (e.g., `0.2` = 20%, `0.5` = 50%, default `0.25`) |
| **G** | `yt_title` | YouTube Shorts Title (up to 100 characters) |
| **H** | `yt_description` | YouTube Description (Script automatically adds `#Shorts`) |
| **I** | `yt_tags` | Comma-separated tags (e.g., `ai, automation, shorts, trending`) |
| **J** | `ig_caption` | Caption used for **both** Instagram Reel and Facebook Page Reel |
| **K** | `ig_hashtags` | Hashtags used for **both** Instagram Reel and Facebook Page Reel |
| **L** | `yt_link` | *(Filled by script)* Link to the uploaded YouTube Short |
| **M** | `ig_id` | *(Filled by script)* Instagram Reel Media ID |
| **N** | `fb_id` | *(Filled by script)* Facebook Page Reel Video ID |
| **O** | `log` | *(Filled by script)* Timestamp & execution message |

> 💡 **Important for Google Drive Links:**
> Make sure your video and audio files in Google Drive have their sharing setting set to **"Anyone with the link can view"**, so the cloud runner can download them!

---

## 🔑 2. Google Cloud & Service Account (For Sheet Access)

1. Open [Google Cloud Console](https://console.cloud.google.com/).
2. Create a free project (e.g. `Social Automation`).
3. Enable the **Google Sheets API** and **Google Drive API**.
4. Go to **APIs & Services > Credentials > Create Credentials > Service Account**.
   - Name it `sheet-robot`. Click **Done**.
5. Click on the created service account, go to the **Keys** tab, click **Add Key > Create new key > JSON**.
6. A JSON file will download. Open it in Notepad. You will paste this entire text into GitHub Secrets as `GOOGLE_SERVICE_ACCOUNT_JSON`.
7. **Copy the `client_email`** from that JSON file (looks like `sheet-robot@your-project.iam.gserviceaccount.com`).
8. Open your Google Sheet, click **Share**, and paste this email as an **Editor**.

---

## 🎥 3. YouTube Data API Setup

1. In the same Google Cloud Console project, enable the **YouTube Data API v3**.
2. Go to **OAuth Consent Screen**:
   - User Type: **External**
   - Fill App Name (e.g., `My Auto Uploader`) and your email.
   - Under **Test Users**, add your own Gmail address that owns the YouTube channel.
3. Go to **Credentials > Create Credentials > OAuth Client ID**:
   - Application Type: **Desktop App**
   - Click **Create**.
   - Copy the **Client ID** and **Client Secret**.
4. **Generate One-Time Refresh Token:**
   - In terminal/PowerShell, run:
     ```powershell
     python get_youtube_token.py
     ```
   - Enter your Client ID and Client Secret.
   - Your browser will open; log into your YouTube account and click **Allow**.
   - The script will print your `YT_REFRESH_TOKEN`.

---

## 📸 4. Meta Setup: Instagram & Facebook Page Graph API

Because Facebook and Instagram are both owned by Meta, you set them up together inside **Meta for Developers**:

1. Switch your Instagram account to a **Professional (Creator or Business) Account**.
2. Link your Instagram account to your **Facebook Page** (via Instagram Mobile Settings or Meta Business Suite).
3. Go to [Meta for Developers](https://developers.facebook.com/) and create a free App (Type: **Business**).
4. Add the **Instagram Graph API** product.
5. In the **Graph API Explorer** (`https://developers.facebook.com/tools/explorer`):
   - Select your App.
   - Add these permissions:
     - `instagram_basic`
     - `instagram_content_publish`
     - `pages_show_list`
     - `pages_read_engagement`
     - `pages_manage_posts`
   - Click **Generate Access Token**.
   - **Find your IDs:**
     - Run: `GET me/accounts?fields=name,id,access_token,instagram_business_account`
     - You will see:
       - `id`: This is your **`FB_PAGE_ID`**.
       - `access_token`: This is your **`FB_PAGE_ACCESS_TOKEN`**.
       - `instagram_business_account.id`: This is your **`IG_USER_ID`**.
6. **Extend to Long-Lived Token (60 days):**
   - Go to the **Access Token Tool** in Meta for Developers.
   - Click **Extend Access Token** for your token.
   - Copy this long-lived token as **`IG_ACCESS_TOKEN`** (and page token if provided).

---

## 🔒 5. Add Secrets to GitHub

In your GitHub repository (`iamrutvikbarot/yt-studio-scheduler`):
1. Go to **Settings > Secrets and variables > Actions > New repository secret**.
2. Add the following **8 secrets**:

| Secret Name | Value |
| :--- | :--- |
| `GOOGLE_SHEET_ID` | The string between `/d/` and `/edit` in your Google Sheet URL |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | The entire content of your downloaded Google Service Account JSON file |
| `YT_CLIENT_ID` | Your Google OAuth Client ID |
| `YT_CLIENT_SECRET` | Your Google OAuth Client Secret |
| `YT_REFRESH_TOKEN` | The token generated by `get_youtube_token.py` |
| `IG_USER_ID` | Your Instagram Business Account ID |
| `IG_ACCESS_TOKEN` | Your Meta Long-Lived User Access Token |
| `FB_PAGE_ID` | Your Facebook Page ID |
| `FB_PAGE_ACCESS_TOKEN` | *(Optional)* Your Facebook Page Access Token (if omitted, the script automatically exchanges it using your `IG_ACCESS_TOKEN`!) |

---

## ⚡ 6. How It Operates

1. **Add a Row:** Fill your details in the Google Sheet (Video URL, optional Music URL, YouTube details, Instagram caption & hashtags) and set `status` to `PENDING`.
2. **Automated Trigger:**
   - Every 30 minutes, GitHub Actions automatically runs.
   - Or, go to **GitHub > Actions > Shorts & Reels Auto-Scheduler > Run workflow** to trigger it immediately.
3. **Execution:**
   - The runner downloads the video & music.
   - FFmpeg mixes them with the volume you picked.
   - YouTube schedules the Short for your exact time.
   - Instagram schedules the Reel for your exact time.
   - Facebook Page schedules the Reel for your exact time using the same caption & hashtags.
   - The Google Sheet row is updated to `SCHEDULED` with the YouTube link, Instagram Media ID, and Facebook Video ID!
