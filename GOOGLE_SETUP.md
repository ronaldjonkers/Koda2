# Google API Setup Guide

This guide explains how to set up Google Calendar and Gmail integration.

## Where to Place Credentials

Google credentials files should be placed in the `config/` directory:

```
Koda2/
├── config/
│   ├── google_credentials.json     # OAuth credentials (you download this)
│   └── google_token.json           # Auto-generated after first auth
├── .env
└── ...
```

## Step-by-Step Setup

### 1. Create a Google Cloud Project

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Click "Select a project" → "New Project"
3. Enter project name (e.g., "Koda2 Assistant")
4. Click "Create"

### 2. Enable APIs

1. In your project, go to "APIs & Services" → "Library"
2. Search for and enable these APIs:
   - **Google Calendar API**
   - **Gmail API**
   - **Google People API** (optional, for contacts)

### 3. Create OAuth Credentials

1. Go to "APIs & Services" → "Credentials"
2. Click "Create Credentials" → "OAuth client ID"
3. If prompted, configure the consent screen:
   - User Type: "External"
   - App name: "Koda2"
   - User support email: your email
   - Developer contact: your email
4. For Application type, select "Desktop app"
5. Name: "Koda2 Desktop"
6. Click "Create"
7. Click "Download JSON"

### 4. Place the File

Rename the downloaded file to `google_credentials.json` and move it to:
```
config/google_credentials.json
```

### 5. First Run

On first run, Koda2 will:
1. Open a browser window for Google authentication
2. Ask you to grant permissions
3. Save the access token to `config/google_token.json`

You only need to do this once!

## Troubleshooting

### "Error 403: Access Denied"
Your app is in testing mode. Either:
- Add your email as a test user in OAuth consent screen
- Or publish the app (requires verification for external users)

### "Token expired"
Delete `config/google_token.json` and restart Koda2. It will re-authenticate.

### "File not found"
Make sure `config/google_credentials.json` exists and contains valid JSON.

## Security Notes

- Never commit `google_credentials.json` or `google_token.json` to git!
- These files are already in `.gitignore`
- The token file contains access credentials - keep it secure
