/**
 * YouTube Shorts Related Video & Pin Comment Automation (Multi-Channel + Gmail Alerts)
 * ------------------------------------------------------------------------------------
 * 100% Free | Runs 24x7 via Google Apps Script Time Trigger | Official YouTube API v3
 *
 * Features:
 * - Tracks unlimited YouTube channels from a single Google Sheet
 * - Uses 0-quota RSS polling; only calls YouTube Data API v3 when a new upload appears
 * - Classifies Shorts vs. Long videos cleanly by duration (<= SHORT_MAX_SECONDS = Short)
 * - Auto-updates each channel's latest Long video and pairs upcoming Shorts with it
 * - Auto-posts comments (via built-in YouTube service OR per-channel OAuth Refresh Token)
 * - Sends clean HTML Gmail alerts with 1-click buttons for "Set Related Video" & "Pin Comment"
 */

const SHEET_NAMES = {
  CONFIG: 'Config',
  CHANNELS: 'Channels',
  LOG: 'Videos_Log'
};

// Column indices (1-based) for the Channels tab
const CH_COL = {
  ACTIVE: 1,
  NAME: 2,
  CHANNEL_ID: 3,
  LONG_ID: 4,
  LONG_TITLE: 5,
  LONG_URL: 6,
  AUTO_COMMENT: 7,
  CUSTOM_TEMPLATE: 8,
  CUSTOM_EMAIL: 9,
  REFRESH_TOKEN: 10,
  LAST_CHECKED: 11
};

// ============================================================================
// 1. CUSTOM MENU IN GOOGLE SHEETS
// ============================================================================

function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu('YT Automation')
    .addItem('1. Setup / Format Sheet Tabs', 'setupSheetTemplate')
    .addItem('2. Initialize Existing Videos (Run Once)', 'initializeExistingVideos')
    .addSeparator()
    .addItem('3. Check All Channels Now', 'checkAllChannels')
    .addItem('4. Send Test Gmail Alert', 'sendTestEmailAlert')
    .addSeparator()
    .addItem('5. Start 24x7 Trigger (Every 5 Min)', 'installTrigger')
    .addItem('6. Stop 24x7 Trigger', 'removeTriggers')
    .addToUi();
}

// ============================================================================
// 2. ONE-CLICK SHEET TEMPLATE SETUP (SAFE: PRESERVES EXISTING DATA)
// ============================================================================

function setupSheetTemplate() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const defaultEmail = Session.getActiveUser().getEmail() || '';

  // --- Tab 1: Config ---
  let configSheet = ss.getSheetByName(SHEET_NAMES.CONFIG);
  if (!configSheet) {
    configSheet = ss.insertSheet(SHEET_NAMES.CONFIG);
  }
  const configDefaults = [
    ['Setting', 'Value', 'Description'],
    ['SHORT_MAX_SECONDS', 180, 'Max duration (seconds) to classify a video as a Short (YouTube Shorts max is 180s)'],
    ['DEFAULT_ALERT_EMAIL', defaultEmail, 'Gmail address for 1-click alerts (you can add multiple separated by commas)'],
    ['DEFAULT_COMMENT_TEMPLATE', 'Watch the full video (tap the Related Video link above! 👆) — {{LONG_TITLE}} {{LONG_URL}}', 'Supports {{LONG_TITLE}} and {{LONG_URL}}'],
    ['AUTO_UPDATE_DESCRIPTION', 'NO', 'YES = also append the Long video link to the Short description'],
    ['NOTIFY_ON_LONG_VIDEO', 'NO', 'YES = also send an email when a new Long video is detected'],
    ['OAUTH_CLIENT_ID', '', 'Optional: Google Cloud OAuth Client ID (only needed for per-channel Refresh Tokens)'],
    ['OAUTH_CLIENT_SECRET', '', 'Optional: Google Cloud OAuth Client Secret (only needed for per-channel Refresh Tokens)']
  ];

  // Preserve any existing Config values the user already entered
  const existingConfig = {};
  if (configSheet.getLastRow() > 1) {
    const existingRows = configSheet.getRange(2, 1, configSheet.getLastRow() - 1, 2).getValues();
    existingRows.forEach(function (row) {
      const key = String(row[0] || '').trim();
      const val = row[1];
      if (key && !isPlaceholder_(val)) {
        existingConfig[key] = val;
      }
    });
  }

  configSheet.clearContents();
  const mergedConfig = configDefaults.map(function (row, idx) {
    if (idx === 0) return row;
    const key = row[0];
    if (existingConfig.hasOwnProperty(key) && String(existingConfig[key]).trim() !== '') {
      return [key, existingConfig[key], row[2]];
    }
    return row;
  });
  configSheet.getRange(1, 1, mergedConfig.length, 3).setValues(mergedConfig);
  formatHeaderRow_(configSheet, 3);
  configSheet.setColumnWidth(1, 240);
  configSheet.setColumnWidth(2, 420);
  configSheet.setColumnWidth(3, 460);

  // --- Tab 2: Channels ---
  let chSheet = ss.getSheetByName(SHEET_NAMES.CHANNELS);
  if (!chSheet) {
    chSheet = ss.insertSheet(SHEET_NAMES.CHANNELS);
  }
  const chHeaders = [[
    'Active',
    'Channel Name',
    'Channel ID',
    'Current Long Video ID',
    'Current Long Video Title',
    'Current Long Video URL',
    'Auto Comment',
    'Custom Comment Template',
    'Custom Alert Email',
    'Refresh Token',
    'Last Checked'
  ]];
  chSheet.getRange(1, 1, 1, chHeaders[0].length).setValues(chHeaders);
  formatHeaderRow_(chSheet, chHeaders[0].length);
  chSheet.setFrozenRows(1);

  // Add checkboxes in Column A (rows 2 to 50) & YES/NO dropdown in Column G
  chSheet.getRange('A2:A50').insertCheckboxes();
  const yesNoRule = SpreadsheetApp.newDataValidation()
    .requireValueInList(['YES', 'NO'], true)
    .setAllowInvalid(false)
    .build();
  chSheet.getRange('G2:G50').setDataValidation(yesNoRule);
  chSheet.setColumnWidth(1, 65);
  chSheet.setColumnWidth(2, 180);
  chSheet.setColumnWidth(3, 220);
  chSheet.setColumnWidth(4, 160);
  chSheet.setColumnWidth(5, 240);
  chSheet.setColumnWidth(6, 220);
  chSheet.setColumnWidth(7, 115);
  chSheet.setColumnWidth(8, 260);
  chSheet.setColumnWidth(9, 240);
  chSheet.setColumnWidth(10, 180);
  chSheet.setColumnWidth(11, 160);

  // --- Tab 3: Videos_Log ---
  let logSheet = ss.getSheetByName(SHEET_NAMES.LOG);
  if (!logSheet) {
    logSheet = ss.insertSheet(SHEET_NAMES.LOG);
  }
  const logHeaders = [[
    'Detected At',
    'Channel Name',
    'Channel ID',
    'Video ID',
    'Video Type',
    'Title',
    'Video URL',
    'Linked Long Video ID',
    'Linked Long Video URL',
    'Comment Status',
    'Comment ID',
    'Related Video Link',
    'Pin Comment Link',
    'Manual Steps Done',
    'Notes'
  ]];
  logSheet.getRange(1, 1, 1, logHeaders[0].length).setValues(logHeaders);
  formatHeaderRow_(logSheet, logHeaders[0].length);
  logSheet.setFrozenRows(1);
  logSheet.setColumnWidth(1, 155);
  logSheet.setColumnWidth(2, 160);
  logSheet.setColumnWidth(4, 125);
  logSheet.setColumnWidth(5, 90);
  logSheet.setColumnWidth(6, 260);
  logSheet.setColumnWidth(10, 130);
  logSheet.setColumnWidth(12, 260);
  logSheet.setColumnWidth(13, 240);
  logSheet.setColumnWidth(14, 130);
  logSheet.setColumnWidth(15, 240);

  notifyUi_(
    'Setup Complete',
    'All 3 tabs (Config, Channels, Videos_Log) are ready!\n\nNext steps:\n1. Check your email in Config!B3 (DEFAULT_ALERT_EMAIL)\n2. Run "YT Automation -> 4. Send Test Gmail Alert" to test\n3. Add your channels in the Channels tab (tick Active = TRUE)\n4. Run "YT Automation -> 2. Initialize Existing Videos (Run Once)"'
  );
}

// ============================================================================
// 3. INITIALIZE EXISTING VIDEOS (PREVENTS SPAMMING OLD SHORTS ON DAY 1)
// ============================================================================

function initializeExistingVideos() {
  runPipeline_(true);
  notifyUi_(
    'Initialization Complete',
    'All current videos from your active channels have been logged safely without posting comments or sending emails.\n\nEach channel\'s latest Long video has been saved in the Channels tab.\nNow run "YT Automation -> 5. Start 24x7 Trigger (Every 5 Min)".'
  );
}

// ============================================================================
// 4. MAIN 24x7 FUNCTION (CALLED BY TIME TRIGGER EVERY 5 MINUTES)
// ============================================================================

function checkAllChannels() {
  runPipeline_(false);
}

function runPipeline_(isInitialSync) {
  const lock = LockService.getScriptLock();
  if (!lock.tryLock(15000)) {
    Logger.log('Another execution is already running. Skipping this cycle.');
    return;
  }

  try {
    const ss = SpreadsheetApp.getActiveSpreadsheet();
    const config = readConfig_(ss);
    const chSheet = ss.getSheetByName(SHEET_NAMES.CHANNELS);
    const logSheet = ss.getSheetByName(SHEET_NAMES.LOG);

    if (!chSheet || !logSheet) {
      throw new Error('Missing Channels or Videos_Log tab. Run "Setup / Format Sheet Tabs" first.');
    }

    const existingVideoIds = getLoggedVideoIds_(logSheet);
    const lastChRow = chSheet.getLastRow();
    if (lastChRow < 2) {
      Logger.log('No channels found in Channels tab.');
      return;
    }

    const channelRows = chSheet.getRange(2, 1, lastChRow - 1, CH_COL.LAST_CHECKED).getValues();
    const shortMaxSeconds = Number(config.SHORT_MAX_SECONDS) || 180;

    for (let i = 0; i < channelRows.length; i++) {
      const rowNum = i + 2;
      const row = channelRows[i];

      const isActive = row[CH_COL.ACTIVE - 1] === true || String(row[CH_COL.ACTIVE - 1]).toUpperCase() === 'TRUE';
      const channelName = String(row[CH_COL.NAME - 1] || '').trim() || ('Channel ' + (i + 1));
      const channelId = String(row[CH_COL.CHANNEL_ID - 1] || '').trim();

      if (!isActive || !channelId) {
        continue;
      }

      const channelState = {
        rowNum: rowNum,
        name: channelName,
        channelId: channelId,
        longId: cleanVal_(row[CH_COL.LONG_ID - 1]),
        longTitle: cleanVal_(row[CH_COL.LONG_TITLE - 1]),
        longUrl: cleanVal_(row[CH_COL.LONG_URL - 1]),
        autoComment: String(row[CH_COL.AUTO_COMMENT - 1] || 'YES').trim().toUpperCase() === 'YES',
        commentTemplate: cleanVal_(row[CH_COL.CUSTOM_TEMPLATE - 1]) || config.DEFAULT_COMMENT_TEMPLATE,
        alertEmail: cleanVal_(row[CH_COL.CUSTOM_EMAIL - 1]) || config.DEFAULT_ALERT_EMAIL,
        refreshToken: cleanVal_(row[CH_COL.REFRESH_TOKEN - 1])
      };

      try {
        processSingleChannel_(chSheet, logSheet, config, channelState, existingVideoIds, shortMaxSeconds, isInitialSync);
        chSheet.getRange(rowNum, CH_COL.LAST_CHECKED).setValue(new Date());
      } catch (err) {
        Logger.log('Error processing channel "' + channelName + '" (' + channelId + '): ' + err.message);
      }
    }
  } finally {
    lock.releaseLock();
  }
}

function processSingleChannel_(chSheet, logSheet, config, ch, existingVideoIds, shortMaxSeconds, isInitialSync) {
  // Step 1: Poll 0-quota RSS feed
  const feedEntries = fetchRssEntries_(ch.channelId);
  if (!feedEntries.length) {
    return;
  }

  // Filter strictly to videos we have never seen before
  const unseenEntries = feedEntries.filter(function (entry) {
    return !existingVideoIds.has(entry.videoId);
  });

  if (!unseenEntries.length) {
    return;
  }

  // Sort oldest -> newest so a Long video uploaded right before a Short is processed FIRST
  unseenEntries.sort(function (a, b) {
    return a.publishedMs - b.publishedMs;
  });

  // Step 2: Fetch video metadata in a single batched YouTube API call (1 quota unit)
  const videoIds = unseenEntries.map(function (e) { return e.videoId; });
  const detailsMap = fetchVideoDetailsBatch_(videoIds);

  let accessTokenCache = null;
  const hadPreConfiguredLongId = !!ch.longId;

  for (let i = 0; i < unseenEntries.length; i++) {
    const entry = unseenEntries[i];
    const details = detailsMap[entry.videoId];

    // If video metadata isn't ready yet or it's an upcoming scheduled premiere/live stream, skip for now
    if (!details) {
      continue;
    }
    const liveStatus = (details.snippet && details.snippet.liveBroadcastContent) || 'none';
    const durationSeconds = parseIsoDurationSeconds_(details.contentDetails && details.contentDetails.duration);
    if (liveStatus === 'upcoming' || durationSeconds === 0) {
      continue;
    }

    const title = (details.snippet && details.snippet.title) || entry.title;
    const isShort = detectIfShort_(entry.videoId, durationSeconds, shortMaxSeconds);
    const videoType = isShort ? 'SHORT' : 'LONG';
    const videoUrl = isShort
      ? 'https://www.youtube.com/shorts/' + entry.videoId
      : 'https://youtu.be/' + entry.videoId;

    // --- CASE A: LONG VIDEO ---
    if (!isShort) {
      // During initial sync, keep any manually entered Long Video ID; otherwise keep advancing
      // oldest -> newest so we end up with the channel's most recent Long video.
      if (!isInitialSync || !hadPreConfiguredLongId) {
        ch.longId = entry.videoId;
        ch.longTitle = title;
        ch.longUrl = 'https://youtu.be/' + entry.videoId;
        chSheet.getRange(ch.rowNum, CH_COL.LONG_ID, 1, 3).setValues([[ch.longId, ch.longTitle, ch.longUrl]]);
      }

      appendLogRow_(logSheet, {
        channelName: ch.name,
        channelId: ch.channelId,
        videoId: entry.videoId,
        videoType: videoType,
        title: title,
        videoUrl: videoUrl,
        linkedLongId: '',
        linkedLongUrl: '',
        commentStatus: isInitialSync ? 'INITIALIZED' : 'N/A (Long)',
        commentId: '',
        studioLink: 'https://studio.youtube.com/video/' + entry.videoId + '/edit',
        pinLink: '',
        done: true,
        notes: isInitialSync ? 'Existing video logged during setup' : 'Updated as active Long video'
      });

      existingVideoIds.add(entry.videoId);

      if (!isInitialSync && String(config.NOTIFY_ON_LONG_VIDEO).toUpperCase() === 'YES' && ch.alertEmail) {
        sendLongVideoEmailAlert_(ch.alertEmail, ch.name, title, videoUrl);
      }
      continue;
    }

    // --- CASE B: SHORT VIDEO ---
    const studioLink = 'https://studio.youtube.com/video/' + entry.videoId + '/edit';
    const pinLink = 'https://www.youtube.com/shorts/' + entry.videoId;

    if (isInitialSync) {
      appendLogRow_(logSheet, {
        channelName: ch.name,
        channelId: ch.channelId,
        videoId: entry.videoId,
        videoType: 'SHORT',
        title: title,
        videoUrl: videoUrl,
        linkedLongId: '',
        linkedLongUrl: '',
        commentStatus: 'INITIALIZED',
        commentId: '',
        studioLink: studioLink,
        pinLink: pinLink,
        done: true,
        notes: 'Existing Short skipped during initial sync'
      });
      existingVideoIds.add(entry.videoId);
      continue;
    }

    const longId = ch.longId;
    const longTitle = ch.longTitle || 'Full Video';
    const longUrl = ch.longUrl || (longId ? 'https://youtu.be/' + longId : '');

    const commentText = renderTemplate_(ch.commentTemplate, longTitle, longUrl);
    let commentStatus = 'SKIPPED';
    let commentId = '';
    const notesList = [];

    if (!longId) {
      commentStatus = 'NO_LONG_VIDEO';
      notesList.push('No Current Long Video set in Channels tab yet');
    } else if (ch.autoComment) {
      try {
        if (ch.refreshToken && config.OAUTH_CLIENT_ID && config.OAUTH_CLIENT_SECRET) {
          if (!accessTokenCache) {
            accessTokenCache = exchangeRefreshToken_(config.OAUTH_CLIENT_ID, config.OAUTH_CLIENT_SECRET, ch.refreshToken);
          }
          commentId = postCommentWithBearer_(entry.videoId, commentText, accessTokenCache);
        } else {
          commentId = postCommentBuiltIn_(entry.videoId, commentText);
        }
        commentStatus = 'POSTED';
      } catch (err) {
        commentStatus = 'ERROR';
        notesList.push('Comment error: ' + err.message);
      }

      // Optional: also append Long video URL to Short description
      if (String(config.AUTO_UPDATE_DESCRIPTION).toUpperCase() === 'YES') {
        try {
          appendLinkToDescription_(details, longTitle, longUrl, accessTokenCache);
          notesList.push('Description updated');
        } catch (descErr) {
          notesList.push('Description error: ' + descErr.message);
        }
      }
    } else {
      commentStatus = 'MANUAL';
      notesList.push('Auto Comment is set to NO');
    }

    appendLogRow_(logSheet, {
      channelName: ch.name,
      channelId: ch.channelId,
      videoId: entry.videoId,
      videoType: 'SHORT',
      title: title,
      videoUrl: videoUrl,
      linkedLongId: longId,
      linkedLongUrl: longUrl,
      commentStatus: commentStatus,
      commentId: commentId,
      studioLink: studioLink,
      pinLink: pinLink,
      done: false,
      notes: notesList.join(' | ')
    });

    existingVideoIds.add(entry.videoId);

    // Send HTML Gmail Alert with 2 clickable buttons
    if (ch.alertEmail) {
      try {
        sendShortEmailAlert_(ch.alertEmail, {
          channelName: ch.name,
          shortTitle: title,
          shortId: entry.videoId,
          longTitle: longTitle,
          longUrl: longUrl,
          commentStatus: commentStatus,
          commentText: commentText,
          studioLink: studioLink,
          pinLink: pinLink,
          notes: notesList.join(' | ')
        });
      } catch (mailErr) {
        Logger.log('Gmail alert error: ' + mailErr.message);
      }
    }
  }
}

// ============================================================================
// 5. YOUTUBE RSS & DATA API v3 HELPERS
// ============================================================================

function fetchRssEntries_(channelId) {
  const rssUrl = 'https://www.youtube.com/feeds/videos.xml?channel_id=' + encodeURIComponent(channelId);
  const response = UrlFetchApp.fetch(rssUrl, { muteHttpExceptions: true });
  if (response.getResponseCode() !== 200) {
    throw new Error('RSS fetch failed (HTTP ' + response.getResponseCode() + ') for channel ' + channelId);
  }

  const doc = XmlService.parse(response.getContentText());
  const root = doc.getRootElement();
  const atomNs = XmlService.getNamespace('http://www.w3.org/2005/Atom');
  const ytNs = XmlService.getNamespace('yt', 'http://www.youtube.com/xml/schemas/2015');

  const entries = root.getChildren('entry', atomNs);
  return entries.map(function (entry) {
    const videoId = entry.getChildText('videoId', ytNs);
    const title = entry.getChildText('title', atomNs) || '';
    const publishedStr = entry.getChildText('published', atomNs) || '';
    return {
      videoId: videoId,
      title: title,
      publishedMs: publishedStr ? new Date(publishedStr).getTime() : Date.now()
    };
  }).filter(function (e) {
    return !!e.videoId;
  });
}

function fetchVideoDetailsBatch_(videoIds) {
  if (typeof YouTube === 'undefined') {
    throw new Error('YouTube Data API v3 service is not enabled! Update appsscript.json or click Services + -> YouTube Data API v3.');
  }

  const map = {};
  for (let i = 0; i < videoIds.length; i += 50) {
    const chunk = videoIds.slice(i, i + 50);
    const res = YouTube.Videos.list('snippet,contentDetails,status', {
      id: chunk.join(',')
    });
    const items = (res && res.items) || [];
    items.forEach(function (item) {
      map[item.id] = item;
    });
  }
  return map;
}

/**
 * Classifies a video as a Short strictly by duration:
 * - durationSeconds <= shortMaxSeconds (default 180s) => SHORT
 * - durationSeconds > shortMaxSeconds                 => LONG
 */
function detectIfShort_(videoId, durationSeconds, shortMaxSeconds) {
  return durationSeconds > 0 && durationSeconds <= shortMaxSeconds;
}

function parseIsoDurationSeconds_(iso) {
  if (!iso) return 0;
  const match = String(iso).match(/PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?/);
  if (!match) return 0;
  const hours = parseInt(match[1] || '0', 10);
  const minutes = parseInt(match[2] || '0', 10);
  const seconds = parseInt(match[3] || '0', 10);
  return hours * 3600 + minutes * 60 + seconds;
}

function postCommentBuiltIn_(videoId, commentText) {
  const resource = {
    snippet: {
      videoId: videoId,
      topLevelComment: {
        snippet: {
          textOriginal: commentText
        }
      }
    }
  };
  const response = YouTube.CommentThreads.insert(resource, 'snippet');
  return (response && response.id) || '';
}

function postCommentWithBearer_(videoId, commentText, accessToken) {
  const url = 'https://www.googleapis.com/youtube/v3/commentThreads?part=snippet';
  const payload = {
    snippet: {
      videoId: videoId,
      topLevelComment: {
        snippet: {
          textOriginal: commentText
        }
      }
    }
  };
  const response = UrlFetchApp.fetch(url, {
    method: 'post',
    contentType: 'application/json',
    headers: { Authorization: 'Bearer ' + accessToken },
    payload: JSON.stringify(payload),
    muteHttpExceptions: true
  });
  const code = response.getResponseCode();
  const data = JSON.parse(response.getContentText() || '{}');
  if (code < 200 || code >= 300) {
    const errMsg = (data.error && data.error.message) || ('HTTP ' + code);
    throw new Error(errMsg);
  }
  return data.id || '';
}

function appendLinkToDescription_(videoDetails, longTitle, longUrl, accessToken) {
  if (!longUrl) return;
  const snippet = videoDetails.snippet || {};
  const currentDesc = snippet.description || '';
  if (currentDesc.indexOf(longUrl) !== -1) {
    return;
  }

  const updatedSnippet = {
    title: snippet.title,
    categoryId: snippet.categoryId,
    description: (currentDesc ? currentDesc + '\n\n' : '') + 'Full Video: ' + longTitle + '\n' + longUrl
  };
  if (snippet.tags) updatedSnippet.tags = snippet.tags;
  if (snippet.defaultLanguage) updatedSnippet.defaultLanguage = snippet.defaultLanguage;

  const body = { id: videoDetails.id, snippet: updatedSnippet };

  if (accessToken) {
    const res = UrlFetchApp.fetch('https://www.googleapis.com/youtube/v3/videos?part=snippet', {
      method: 'put',
      contentType: 'application/json',
      headers: { Authorization: 'Bearer ' + accessToken },
      payload: JSON.stringify(body),
      muteHttpExceptions: true
    });
    if (res.getResponseCode() < 200 || res.getResponseCode() >= 300) {
      throw new Error('HTTP ' + res.getResponseCode() + ': ' + res.getContentText());
    }
  } else {
    YouTube.Videos.update(body, 'snippet');
  }
}

function exchangeRefreshToken_(clientId, clientSecret, refreshToken) {
  const response = UrlFetchApp.fetch('https://oauth2.googleapis.com/token', {
    method: 'post',
    payload: {
      client_id: clientId,
      client_secret: clientSecret,
      refresh_token: refreshToken,
      grant_type: 'refresh_token'
    },
    muteHttpExceptions: true
  });
  const data = JSON.parse(response.getContentText() || '{}');
  if (!data.access_token) {
    throw new Error('OAuth token refresh failed: ' + (data.error_description || data.error || 'Unknown error'));
  }
  return data.access_token;
}

// ============================================================================
// 6. GMAIL ALERTS (HTML EMAIL WITH 2 CLICKABLE BUTTONS)
// ============================================================================

function sendShortEmailAlert_(recipientEmail, info) {
  const statusMap = {
    POSTED: { text: '✅ Comment Posted Automatically', bg: '#e6f4ea', color: '#137333' },
    MANUAL: { text: '📝 Manual Comment (Auto Comment = NO)', bg: '#fef7e0', color: '#b06000' },
    NO_LONG_VIDEO: { text: '⚠️ No Long Video Set Yet', bg: '#fce8e6', color: '#c5221f' }
  };
  const statusStyle = statusMap[info.commentStatus] || {
    text: '❌ Comment Error — Check Notes',
    bg: '#fce8e6',
    color: '#c5221f'
  };

  const subject = '🎬 [' + info.channelName + '] New Short: ' + info.shortTitle;

  const plainBody = [
    'Channel: ' + info.channelName,
    'New Short: ' + info.shortTitle,
    'Linked Long Video: ' + info.longTitle + ' (' + (info.longUrl || 'None') + ')',
    'Comment Status: ' + statusStyle.text,
    'Comment Text: ' + info.commentText,
    info.notes ? 'Notes: ' + info.notes : '',
    '',
    '1. Set Related Video (Studio): ' + info.studioLink,
    '2. Open Short & Pin Comment: ' + info.pinLink
  ].join('\n');

  const htmlBody =
    '<div style="font-family:Arial,Helvetica,sans-serif;max-width:600px;margin:0 auto;border:1px solid #e0e0e0;border-radius:10px;overflow:hidden;">' +
      '<div style="background:#cc0000;color:#ffffff;padding:16px 20px;">' +
        '<div style="font-size:12px;opacity:0.9;text-transform:uppercase;letter-spacing:0.5px;">YouTube Shorts Automation</div>' +
        '<div style="font-size:20px;font-weight:bold;margin-top:4px;">🎬 ' + escapeHtml_(info.channelName) + '</div>' +
      '</div>' +
      '<div style="padding:20px;color:#202124;">' +
        '<div style="margin-bottom:14px;">' +
          '<div style="font-size:12px;color:#5f6368;font-weight:bold;">NEW SHORT UPLOADED</div>' +
          '<div style="font-size:16px;font-weight:bold;margin-top:4px;">' + escapeHtml_(info.shortTitle) + '</div>' +
        '</div>' +
        '<div style="margin-bottom:14px;">' +
          '<div style="font-size:12px;color:#5f6368;font-weight:bold;">LINKED LONG VIDEO</div>' +
          '<div style="font-size:14px;margin-top:4px;">' +
            (info.longUrl
              ? '<a href="' + info.longUrl + '" style="color:#1a73e8;text-decoration:none;">' + escapeHtml_(info.longTitle) + '</a>'
              : '<i>None set in Channels tab</i>') +
          '</div>' +
        '</div>' +
        '<div style="margin-bottom:16px;">' +
          '<span style="display:inline-block;padding:6px 10px;border-radius:6px;font-size:13px;font-weight:bold;background:' + statusStyle.bg + ';color:' + statusStyle.color + ';">' +
            statusStyle.text +
          '</span>' +
        '</div>' +
        '<div style="background:#f8f9fa;border:1px solid #dadce0;border-radius:6px;padding:12px;margin-bottom:18px;">' +
          '<div style="font-size:11px;color:#5f6368;font-weight:bold;margin-bottom:6px;">COMMENT TEXT</div>' +
          '<div style="font-size:14px;line-height:1.5;color:#202124;">' + escapeHtml_(info.commentText) + '</div>' +
        '</div>' +
        (info.notes
          ? '<div style="font-size:12px;color:#b06000;margin-bottom:18px;"><b>Notes:</b> ' + escapeHtml_(info.notes) + '</div>'
          : '') +
        '<div style="margin-top:10px;">' +
          '<a href="' + info.studioLink + '" style="display:inline-block;background:#1a73e8;color:#ffffff;text-decoration:none;font-weight:bold;padding:12px 18px;border-radius:6px;margin-right:10px;margin-bottom:10px;">1. Set Related Video (Studio)</a>' +
          '<a href="' + info.pinLink + '" style="display:inline-block;background:#202124;color:#ffffff;text-decoration:none;font-weight:bold;padding:12px 18px;border-radius:6px;margin-bottom:10px;">2. Open Short &amp; Pin Comment</a>' +
        '</div>' +
      '</div>' +
    '</div>';

  MailApp.sendEmail({
    to: recipientEmail,
    subject: subject,
    body: plainBody,
    htmlBody: htmlBody
  });
}

function sendLongVideoEmailAlert_(recipientEmail, channelName, title, videoUrl) {
  MailApp.sendEmail({
    to: recipientEmail,
    subject: '📺 [' + channelName + '] New Long Video Set as Active Target',
    body: 'Channel: ' + channelName + '\nNew Long Video: ' + title + '\nURL: ' + videoUrl + '\n\nAll upcoming Shorts on this channel will automatically pair with this Long video.'
  });
}

function sendTestEmailAlert() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const config = readConfig_(ss);
  const recipient = config.DEFAULT_ALERT_EMAIL || Session.getActiveUser().getEmail();

  if (!recipient) {
    notifyUi_('Missing Email', 'Please enter your email address in Config!B3 (DEFAULT_ALERT_EMAIL) first.');
    return;
  }

  sendShortEmailAlert_(recipient, {
    channelName: 'Test Channel',
    shortTitle: 'Sample YouTube Short (Test Alert)',
    shortId: 'dQw4w9WgXcQ',
    longTitle: 'Sample Long Video Title',
    longUrl: 'https://youtu.be/dQw4w9WgXcQ',
    commentStatus: 'POSTED',
    commentText: renderTemplate_(config.DEFAULT_COMMENT_TEMPLATE, 'Sample Long Video Title', 'https://youtu.be/dQw4w9WgXcQ'),
    studioLink: 'https://studio.youtube.com/',
    pinLink: 'https://www.youtube.com/shorts/',
    notes: 'This is a test email from your YT Details Google Sheet!'
  });

  notifyUi_('Test Email Sent!', 'Check your Gmail inbox (' + recipient + ') — you should see an email with 2 clickable buttons.');
}

// ============================================================================
// 7. 24x7 TRIGGER MANAGEMENT
// ============================================================================

function installTrigger() {
  removeTriggers_(true);
  ScriptApp.newTrigger('checkAllChannels')
    .timeBased()
    .everyMinutes(5)
    .create();
  notifyUi_('24x7 Automation Active!', 'The script will now automatically check all active channels every 5 minutes, 24x7.');
}

function removeTriggers() {
  removeTriggers_(false);
}

function removeTriggers_(silent) {
  const triggers = ScriptApp.getProjectTriggers();
  let removed = 0;
  triggers.forEach(function (t) {
    if (t.getHandlerFunction() === 'checkAllChannels') {
      ScriptApp.deleteTrigger(t);
      removed++;
    }
  });
  if (!silent) {
    notifyUi_('Trigger Stopped', 'Removed ' + removed + ' scheduled trigger(s).');
  }
}

// ============================================================================
// 8. UTILITY HELPERS
// ============================================================================

function readConfig_(ss) {
  const sheet = ss.getSheetByName(SHEET_NAMES.CONFIG);
  const config = {};
  if (!sheet || sheet.getLastRow() < 2) return config;

  const rows = sheet.getRange(2, 1, sheet.getLastRow() - 1, 2).getValues();
  rows.forEach(function (r) {
    const key = String(r[0] || '').trim();
    if (key) {
      config[key] = cleanVal_(r[1]);
    }
  });
  return config;
}

function getLoggedVideoIds_(logSheet) {
  const ids = new Set();
  const lastRow = logSheet.getLastRow();
  if (lastRow < 2) return ids;

  // Video ID is Column D (4)
  const values = logSheet.getRange(2, 4, lastRow - 1, 1).getValues();
  values.forEach(function (row) {
    const id = String(row[0] || '').trim();
    if (id) ids.add(id);
  });
  return ids;
}

function appendLogRow_(logSheet, data) {
  const row = [
    new Date(),
    data.channelName,
    data.channelId,
    data.videoId,
    data.videoType,
    data.title,
    data.videoUrl,
    data.linkedLongId,
    data.linkedLongUrl,
    data.commentStatus,
    data.commentId,
    data.studioLink,
    data.pinLink,
    data.done,
    data.notes
  ];
  logSheet.appendRow(row);
  const newRowIndex = logSheet.getLastRow();
  logSheet.getRange(newRowIndex, 14).insertCheckboxes();
}

function renderTemplate_(template, longTitle, longUrl) {
  const base = template || 'Watch the full video (tap the Related Video link above! 👆) — {{LONG_TITLE}} {{LONG_URL}}';
  return base
    .replace(/\{\{LONG_TITLE\}\}/g, longTitle || '')
    .replace(/\{\{LONG_URL\}\}/g, longUrl || '')
    .trim();
}

function cleanVal_(val) {
  const s = String(val === null || val === undefined ? '' : val).trim();
  return isPlaceholder_(s) ? '' : s;
}

function isPlaceholder_(val) {
  const s = String(val === null || val === undefined ? '' : val).trim();
  return s.startsWith('(') && s.endsWith(')');
}

function escapeHtml_(text) {
  return String(text || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function formatHeaderRow_(sheet, numCols) {
  sheet.getRange(1, 1, 1, numCols)
    .setBackground('#3b5998')
    .setFontColor('#ffffff')
    .setFontWeight('bold');
}

function notifyUi_(title, message) {
  try {
    SpreadsheetApp.getUi().alert(title, message, SpreadsheetApp.getUi().ButtonSet.OK);
  } catch (e) {
    Logger.log(title + ': ' + message);
  }
}
