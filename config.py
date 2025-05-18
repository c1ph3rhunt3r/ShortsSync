"""
Configuration settings for the TikTok to YouTube Shorts repurposing tool.
"""
import os
from dotenv import load_dotenv
from typing import List, Dict

# Load environment variables
load_dotenv()

# TikTok scraping settings
TIKTOK_SCRAPING = {
    'use_proxy': os.getenv('USE_PROXY', 'false').lower() == 'true',
    'proxy_url': os.getenv('PROXY_URL', ''),
    'request_delay': float(os.getenv('REQUEST_DELAY', '2.0')),  # Delay between requests in seconds
    'retry_attempts': int(os.getenv('RETRY_ATTEMPTS', '3')),    # Number of retries for failed requests
    'timeout': int(os.getenv('REQUEST_TIMEOUT', '30')),         # Request timeout in seconds
}

# YouTube API settings
YOUTUBE_CLIENT_SECRETS_FILE = os.getenv('YOUTUBE_CLIENT_SECRETS_FILE', 'client_secrets.json')
YOUTUBE_SCOPES = [
    'https://www.googleapis.com/auth/youtube.upload',
    'https://www.googleapis.com/auth/youtube.readonly',
    'https://www.googleapis.com/auth/youtube'
]
YOUTUBE_API_SERVICE_NAME = 'youtube'
YOUTUBE_API_VERSION = 'v3'

# Content analysis settings
PERFORMANCE_METRICS = {
    'views': 0.4,       # Weight: 40%
    'likes': 0.3,       # Weight: 30%
    'comments': 0.2,    # Weight: 20%
    'shares': 0.1       # Weight: 10%
}

# Content filters
CONTENT_FILTERS = {
    # Duration filters (important for YouTube Shorts)
    "min_duration": 3,        # Skip videos shorter than 3 seconds
    "max_duration": 60,       # YouTube Shorts must be 60 seconds or less
    
    # Performance thresholds - significantly reduced for better content discovery
    "min_views": 1000,        # Much lower threshold to ensure we get content
    "min_likes": 100,         # Reduced threshold for likes
    "min_shares": 5,          # Very low threshold for shares
    "min_engagement_rate": 0.5,  # Halved the engagement rate requirement
    
    # Content type filters
    "exclude_hashtags": ["#ad", "#sponsored", "#promotion"],  # Avoid reposting sponsored content
    "exclude_keywords": [],    # Add any keywords you want to exclude
    "require_hashtags": [],    # Add any required hashtags here, or leave empty
    
    # Freshness filter (avoid very old content)
    "max_days_old": 180,      # Extended to 6 months for more content options
    
    # Avoid duplicates across channels if same video appears in multiple
    "skip_duplicate_content": True,
    
    # Controversial content caution
    "skip_controversial": False,  # Changed to False to include more content
}

# Reposting settings
REPOSTING_SETTINGS = {
    'max_videos_per_day': int(os.getenv('MAX_VIDEOS_PER_DAY', 3)),
    'video_quality': os.getenv('VIDEO_QUALITY', '720p'),
    'add_watermark': False,
    'add_credits': False,
    'credits_format': 'Original content by @{creator} on TikTok',
    'auto_schedule': True,
    'schedule_times': ['08:00', '12:00', '18:00'],  # UTC times
    'publish_days': ['Monday', 'Wednesday', 'Friday'],
    'file_retention_days': int(os.getenv('FILE_RETENTION_DAYS', 7))  # How many days to keep downloaded/processed files
}

# YouTube upload defaults
YOUTUBE_DEFAULTS = {
    'title_format': '{original_title}',
    'description_format': (
        'Original creator: @{creator}\n'
        '#shorts #{tags}'
    ),
    'category': '22',  # People & Blogs
    'keywords': ['trending', 'viral', 'shorts'],
    'privacy_status': 'public',  # 'public', 'private', or 'unlisted'
    'made_for_kids': False
}

# Proxy settings
PROXY_SETTINGS = {
    'use_proxy': os.getenv('USE_PROXY', 'false').lower() == 'true',
    'proxy_url': os.getenv('PROXY_URL', '')
}

# Logging settings
LOGGING = {
    'level': 'INFO',
    'log_file': 'tiktok_to_youtube.log',
    'log_format': '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
}

def filter_by_content_policy(self, videos: List[Dict]) -> List[Dict]:
    """Filter videos based on the content policy settings."""
    filtered_videos = []
    for video in videos:
        # Duration checks
        duration = float(video.get('video', {}).get('duration', 0))
        if duration < self.filters.get("min_duration", 0) or duration > self.filters.get("max_duration", 60):
            logger.debug(f"Filtered out video (duration {duration}s): {video.get('desc', 'Unknown')}")
            continue
            
        # View count threshold
        views = int(video.get('stats', {}).get('playCount', 0))
        if views < self.filters.get("min_views", 0):
            logger.debug(f"Filtered out video (only {views} views): {video.get('desc', 'Unknown')}")
            continue
            
        # Engagement rate check
        engagement_rate = self.calculate_engagement_rate(video)
        if engagement_rate < self.filters.get("min_engagement_rate", 0):
            logger.debug(f"Filtered out video (low engagement {engagement_rate}%): {video.get('desc', 'Unknown')}")
            continue
            
        # Check excluded hashtags
        caption = video.get('desc', '')
        excluded_tags = self.filters.get("exclude_hashtags", [])
        if any(tag.lower() in caption.lower() for tag in excluded_tags):
            logger.debug(f"Filtered out video (excluded hashtags): {video.get('desc', 'Unknown')}")
            continue
            
        # Passed all filters
        filtered_videos.append(video)
    
    logger.info(f"Filtered down to {len(filtered_videos)} videos from {len(videos)} based on content policy")
    return filtered_videos 