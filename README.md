# ShortsSync

An automated system for scraping popular TikTok videos and uploading them to YouTube Shorts.

> **Note**: This project is still under active development. Updates and changes may be made periodically.

## Features

- Automatically download videos from configured TikTok channels using yt-dlp
- Dynamic view thresholds based on channel size and performance
- YouTube API quota monitoring to prevent hitting limits
- Staggered release schedule support via channel groups
- Configurable retention periods for downloaded/processed videos
- Web dashboard for monitoring system status and performance

## Prerequisites

- Python 3.8 or higher
- A Google Cloud Project with YouTube Data API v3 enabled
- A YouTube channel with permissions to upload videos
- FFmpeg (required for video processing)

## Setup

1. Clone this repository
```bash
git clone https://github.com/yourusername/shortssync.git
cd shortssync
```

2. Create and activate a virtual environment
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. Install dependencies
```bash
pip install -r requirements.txt
```

4. Install FFmpeg:
   - Windows: Download from https://ffmpeg.org/download.html and add to PATH
   - Linux: `sudo apt-get install ffmpeg`
   - macOS: `brew install ffmpeg`

5. Set up configuration files:
   - Create `channels.json` for main configuration
   - Create group-specific files (e.g., `channels-sports.json`)
   - Set up `.env` file with your API credentials

6. YouTube API Setup:
   - Go to Google Cloud Console
   - Create a new project or select existing one
   - Enable YouTube Data API v3
   - Create OAuth 2.0 credentials
   - Download client secrets file as `client_secrets.json`

## Configuration

### Environment Variables (.env)
```
YOUTUBE_API_KEY=your_api_key
CLIENT_ID=your_client_id
CLIENT_SECRET=your_client_secret
```

### Channel Configuration (channels.json)
```json
{
  "channels": [
    "@example_channel1",
    "@example_channel2"
  ],
  "settings": {
    "run_interval": 259200,
    "top": 2,
    "limit": 30,
    "view_threshold": 10000,
    "publish_days": [0, 3, 6]
  }
}
```

## Usage

### Basic Usage
```bash
python main.py
```

### Running Specific Channel Groups
```bash
python main.py --group sports
python main.py --group entertainment
```

### Web Dashboard
Access the monitoring dashboard at http://localhost:8080 when the application is running.

## Maintenance

- Downloaded videos are automatically cleaned up based on retention settings
- YouTube API quota usage is monitored and logged
- Check the dashboard for system status and performance metrics

## Troubleshooting

- If authentication fails, delete the token files and restart the application
- For video download issues, ensure FFmpeg is properly installed and accessible
- Check logs in `shortssync.log` for detailed error information 