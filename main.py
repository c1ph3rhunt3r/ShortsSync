#!/usr/bin/env python3
"""
TikTok to YouTube Shorts Repurposing Tool

This tool automatically scrapes TikTok channels, analyzes content performance,
and reposts the best-performing content to YouTube as Shorts.
"""
import os
import sys
import json
import time
import signal
import asyncio
import logging
import argparse
from typing import List, Dict, Any
from datetime import datetime, timedelta
import shutil

from tiktok_scraper import TikTokScraper
from content_analyzer import ContentAnalyzer
from video_processor import VideoProcessor
from youtube_uploader import YouTubeUploader
from video_history import VideoHistory
import config
from dashboard import start_dashboard_thread, update_processing_stats, record_upload, record_cleanup_operation

# Set up logging
logging.basicConfig(
    level=getattr(logging, config.LOGGING['level']),
    format=config.LOGGING['log_format'],
    handlers=[
        logging.FileHandler(config.LOGGING['log_file']),
        logging.StreamHandler(sys.stdout)  # Add console output
    ]
)
logger = logging.getLogger(__name__)

# Global flag for shutdown
shutdown_requested = False

# Quota tracking variables
QUOTA_LOG_FILE = "youtube_api_quota.json"
DAILY_QUOTA_LIMIT = 10000
# Estimated quota costs per operation
QUOTA_COST = {
    "upload_video": 1600,
    "check_video_exists": 1,
    "get_metrics": 3,
    "list_videos": 1
}

def signal_handler(sig, frame):
    """Handle SIGINT (Ctrl+C) and SIGTERM signals."""
    global shutdown_requested
    logger.info("Shutdown signal received, finishing current tasks before exiting...")
    shutdown_requested = True

def load_channels_config(config_file="channels.json") -> Dict[str, Any]:
    """
    Load channels and settings from the configuration file.
    
    Args:
        config_file (str): Path to the configuration file
        
    Returns:
        Dict[str, Any]: Dictionary containing channels and settings
    """
    try:
        if not os.path.exists(config_file):
            logger.error(f"Configuration file not found: {config_file}")
            default_config = {
                "channels": [],
                "settings": {
                    "metrics": "views,likes,comments,shares",
                    "top": 5,
                    "limit": 50,
                    "download_dir": "downloads",
                    "processed_dir": "processed",
                    "upload": False,
                    "schedule": False,
                    "save_data": True,
                    "add_credits": True,
                    "add_watermark": False,
                    "video_quality": "1080p",  # Higher quality default
                    "run_interval": 3600,  # Default interval: 1 hour
                    "publish_days": None
                }
            }
            
            # Create a default configuration file
            with open(config_file, 'w') as f:
                json.dump(default_config, f, indent=2)
            
            logger.info(f"Created default configuration file: {config_file}")
            return default_config
        
        # Load configuration from file
        with open(config_file, 'r') as f:
            config_data = json.load(f)
        
        # Ensure run_interval exists with a default value if not present
        if "settings" in config_data and "run_interval" not in config_data["settings"]:
            config_data["settings"]["run_interval"] = 3600  # Default: 1 hour
        
        logger.info(f"Loaded configuration from {config_file}")
        return config_data
        
    except Exception as e:
        logger.error(f"Error loading configuration: {str(e)}", exc_info=True)
        sys.exit(1)

async def scrape_tiktok_channels(scraper: TikTokScraper, channels: List[str], limit: int) -> Dict[str, List[Dict[str, Any]]]:
    """
    Scrape videos from TikTok channels.
    
    Args:
        scraper (TikTokScraper): TikTok scraper instance
        channels (List[str]): List of TikTok channel usernames
        limit (int): Maximum number of videos to fetch per channel
        
    Returns:
        Dict[str, List[Dict[str, Any]]]: Dictionary of channel videos by username
    """
    channel_videos = {}
    
    for channel in channels:
        if shutdown_requested:
            logger.info("Shutdown requested, stopping channel scraping")
            break
            
        logger.info(f"Scraping channel: {channel}")
        videos = await scraper.get_channel_videos(channel, limit)
        
        # Clean username (remove @ if present)
        username = channel[1:] if channel.startswith('@') else channel
        channel_videos[username] = videos
        
        logger.info(f"Scraped {len(videos)} videos from {channel}")
    
    return channel_videos

async def process_channels(config_data: Dict[str, Any]):
    """
    Process all channels in the configuration.
    
    Args:
        config_data (Dict[str, Any]): Channel configuration data
    """
    global shutdown_requested
    
    try:
        # Extract settings
        settings = config_data.get("settings", {})
        channels = config_data.get("channels", [])
        
        # Track metrics for processed channels
        total_processed = 0
        total_uploaded = 0
        total_failed = 0
        
        # Initialize module objects
        scraper = TikTokScraper(config_data)
        analyzer = ContentAnalyzer()
        processor = VideoProcessor()
        uploader = YouTubeUploader()
        
        # Log starting session
        log_separator()
        logger.info(f"Starting processing session for {len(channels)} channels")
        
        # Process each channel
        for channel in channels:
            if shutdown_requested:
                logger.info("Shutdown requested, stopping channel processing")
                break
                
            channel_name = channel.get("channel_name", "")
            username = channel.get("username", "")
            limit = channel.get("limit", settings.get("scrape_limit", 20))
            add_watermark = channel.get("add_watermark", settings.get("add_watermark", True))
            add_credits = channel.get("add_credits", settings.get("add_credits", True))
            
            # Skip inactive channels
            if not channel.get("active", True):
                logger.info(f"Skipping inactive channel: {channel_name} (@{username})")
                continue
                
            log_separator()
            logger.info(f"Processing channel: {channel_name} (@{username})")
            
            # 1. Scrape videos
            try:
                videos = await scraper.get_user_videos(username, limit)
                logger.info(f"Retrieved {len(videos)} videos from {username}")
                
                # Update dashboard with channel stats
                if videos:
                    views = [v.get('stats', {}).get('playCount', 0) for v in videos]
                    likes = [v.get('stats', {}).get('diggCount', 0) for v in videos]
                    comments = [v.get('stats', {}).get('commentCount', 0) for v in videos]
                    shares = [v.get('stats', {}).get('shareCount', 0) for v in videos]
                    duration = [v.get('video', {}).get('duration', 0) for v in videos]
                    
                    avg_views = sum(views) / len(views) if views else 0
                    avg_likes = sum(likes) / len(likes) if likes else 0
                    avg_comments = sum(comments) / len(comments) if comments else 0
                    avg_shares = sum(shares) / len(shares) if shares else 0
                    avg_duration = sum(duration) / len(duration) if duration else 0
                    
                    # Calculate engagement rate (likes + comments + shares) / views * 100
                    engagement_metrics = [(likes[i] + comments[i] + shares[i]) / max(1, views[i]) * 100 
                                         for i in range(len(views))]
                    avg_engagement = sum(engagement_metrics) / len(engagement_metrics) if engagement_metrics else 0
                    
                    channel_stats = {
                        "total_videos": len(videos),
                        "avg_views": avg_views,
                        "avg_likes": avg_likes,
                        "avg_comments": avg_comments,
                        "avg_shares": avg_shares,
                        "avg_duration": avg_duration,
                        "avg_engagement_rate": avg_engagement
                    }
                    
                    logger.info(f"Channel {username} statistics: {json.dumps(channel_stats, indent=2)}")
                    
            except Exception as e:
                logger.error(f"Error scraping channel {username}: {str(e)}", exc_info=True)
                continue
                
            # Exit if no videos found
            if not videos:
                logger.warning(f"No videos found for channel {username}")
                continue
                
            # 2. Filter out previously uploaded videos
            filtered_videos = video_history.filter_previously_uploaded(videos, username)
            logger.info(f"Found {len(filtered_videos)} new videos for channel {username}")
            
            if not filtered_videos:
                logger.info(f"No new videos to process for {username}")
                continue
                
            # 3. Analyze and select top videos
            try:
                logger.info(f"Analyzing {len(filtered_videos)} videos from {username}")
                top_videos = analyzer.select_top_videos(
                    filtered_videos, 
                    channel_name,
                    settings.get("top_videos_per_channel", 3)
                )
                
                if not top_videos:
                    logger.warning(f"No videos selected for {username} after content analysis")
                    continue
                    
                # Log selected videos
                for i, video in enumerate(top_videos):
                    views = video.get('stats', {}).get('playCount', 0)
                    likes = video.get('stats', {}).get('diggCount', 0)
                    comments = video.get('stats', {}).get('commentCount', 0)
                    logger.info(f"Channel {username}: Selected #{i+1}: Score: {video.get('engagement_score', 0):.2f}, Views: {views}, Likes: {likes}, Comments: {comments}")
                
            except Exception as e:
                logger.error(f"Error analyzing videos for {username}: {str(e)}", exc_info=True)
                continue
                
            # 4. Download videos
            downloaded_videos = []
            download_data = []
            
            for video in top_videos:
                if shutdown_requested:
                    logger.info("Shutdown requested, stopping video downloads")
                    break
                    
                try:
                    video_url = video.get('url', '')
                    if not video_url:
                        logger.warning(f"Missing URL for video in channel {username}")
                        continue
                        
                    logger.info(f"Downloading video: {video_url}")
                    video_file = await scraper.download_video(video_url, username)
                    
                    if video_file:
                        downloaded_videos.append(video_file)
                        download_data.append(video)
                    else:
                        logger.error(f"Failed to download video: {video_url}")
                        
                except Exception as e:
                    logger.error(f"Error downloading video: {str(e)}", exc_info=True)
            
            # Exit if no videos were downloaded
            if not downloaded_videos:
                logger.warning(f"No videos downloaded for channel {username}")
                continue
                
            # 5. Process videos (add watermark, credits, etc.)
            processed_videos = []
            
            # Skip processing if not adding watermark or credits
            if not add_watermark and not add_credits:
                logger.info(f"Skipping video processing for channel {username} (add_credits={add_credits}, add_watermark={add_watermark})")
                
                # Just copy the original files to processed directory
                for video_file in downloaded_videos:
                    try:
                        # Create output filename with _direct suffix to indicate no processing
                        filename = os.path.basename(video_file)
                        name, ext = os.path.splitext(filename)
                        processed_file = os.path.join("processed", username, f"{name}_direct{ext}")
                        
                        # Create the directory if it doesn't exist
                        os.makedirs(os.path.dirname(processed_file), exist_ok=True)
                        
                        # Copy the file
                        shutil.copy2(video_file, processed_file)
                        logger.info(f"Copied original video to processed directory: {processed_file}")
                        
                        processed_videos.append(processed_file)
                    except Exception as e:
                        logger.error(f"Error copying video file: {str(e)}", exc_info=True)
            else:
                # Process videos with watermark/credits as configured
                for video_file in downloaded_videos:
                    if shutdown_requested:
                        logger.info("Shutdown requested, stopping video processing")
                        break
                        
                    try:
                        logger.info(f"Processing video: {video_file}")
                        
                        # Process the video
                        processed_file = processor.process_video(
                            video_file,
                            add_watermark=add_watermark,
                            add_credits=add_credits,
                            creator=username
                        )
                        
                        if processed_file:
                            processed_videos.append(processed_file)
                            logger.info(f"Successfully processed video: {processed_file}")
                        else:
                            logger.error(f"Failed to process video: {video_file}")
                            
                    except Exception as e:
                        logger.error(f"Error processing video: {str(e)}", exc_info=True)
            
            # Exit if no videos were processed
            if not processed_videos:
                logger.warning(f"No videos processed for channel {username}")
                continue
                
            # 6. Upload videos to YouTube
            if settings.get("upload", True) and not shutdown_requested:
                try:
                    logger.info(f"Uploading {len(processed_videos)} videos to YouTube")
                    upload_results = uploader._upload_immediately(processed_videos, download_data)
                    
                    # Get results
                    successful = upload_results.get("successful", [])
                    failed = upload_results.get("failed", [])
                    
                    logger.info(f"Uploaded {len(successful)} videos, {len(failed)} failed")
                    
                    # Record upload stats for dashboard
                    for video in successful:
                        video_id = video.get("video_id")
                        title = video.get("title", "Unknown title")
                        
                        # Record in video history
                        video_history.record_uploaded_video({
                            "tiktok_url": download_data[0].get('url', ''),
                            "youtube_id": video_id,
                            "title": title,
                            "channel": username,
                            "upload_date": datetime.now().isoformat()
                        })
                        
                        # Update dashboard
                        record_upload(title, username, "success", video_id)
                        
                    for video in failed:
                        title = video.get("title", "Unknown title")
                        record_upload(title, username, "failed")
                    
                    # Update counters
                    total_uploaded += len(successful)
                    total_failed += len(failed)
                    
                except Exception as e:
                    logger.error(f"Error uploading videos: {str(e)}", exc_info=True)
                    total_failed += len(processed_videos)
                    
                    # Record failed uploads
                    for video in download_data:
                        title = video.get('caption', 'Unknown title')
                        record_upload(title, username, "failed")
            else:
                logger.info("Uploads are disabled, skipping upload step")
                
            # Increment processed count
            total_processed += len(processed_videos)
            
        # Log session summary
        log_separator()
        logger.info(f"Processing session complete: {total_processed} videos processed, {total_uploaded} uploaded, {total_failed} failed")
        
        # Update dashboard stats
        update_processing_stats(total_processed, total_uploaded, total_failed)
        logger.info(f"Dashboard stats updated: {total_processed} processed, {total_uploaded} uploaded, {total_failed} failed")
        
        # Run cleanup if enabled
        if settings.get("auto_cleanup", True):
            days_to_keep = settings.get("file_retention_days", 7)
            logger.info("Running scheduled deletion check")
            
            # Check for deleted YouTube videos
            await check_deleted_videos()
            
            # Clean up old files
            await cleanup_old_files("downloads", days_to_keep)
            await cleanup_old_files("processed", days_to_keep)
            
    except Exception as e:
        logger.error(f"Error in process_channels: {str(e)}", exc_info=True)
        
    return total_processed, total_uploaded, total_failed

async def cleanup_old_files(directory: str, days: int):
    """
    Clean up files older than specified days to save disk space.
    
    Args:
        directory (str): Directory path to clean
        days (int): Age in days after which files should be removed
    """
    try:
        if not os.path.exists(directory):
            logger.info(f"Directory does not exist, no cleanup needed: {directory}")
            return {"files_removed": 0, "space_freed_mb": 0}
            
        # Calculate cutoff time
        cutoff_time = time.time() - (days * 86400)  # 86400 seconds in a day
        
        logger.info(f"Cleaning up files older than {days} days in {directory}")
        file_count = 0
        size_cleaned = 0
        
        # Walk through all subdirectories
        for root, dirs, files in os.walk(directory):
            for file in files:
                file_path = os.path.join(root, file)
                
                try:
                    # Check file modification time
                    file_time = os.path.getmtime(file_path)
                    
                    if file_time < cutoff_time:
                        try:
                            # Get file size before deletion for reporting
                            file_size = os.path.getsize(file_path)
                            
                            # Delete the file
                            os.remove(file_path)
                            
                            file_count += 1
                            size_cleaned += file_size
                            
                            logger.debug(f"Deleted old file: {file_path}")
                        except Exception as e:
                            logger.warning(f"Failed to delete file {file_path}: {str(e)}")
                except Exception as e:
                    logger.warning(f"Could not get modification time for {file_path}: {str(e)}")
            
            # Check for and remove empty directories
            for dir_name in dirs[:]:  # Create a copy of dirs to avoid modification during iteration
                dir_path = os.path.join(root, dir_name)
                try:
                    # Check if directory is empty
                    if not os.listdir(dir_path):
                        os.rmdir(dir_path)
                        logger.debug(f"Removed empty directory: {dir_path}")
                except Exception as e:
                    logger.warning(f"Failed to remove empty directory {dir_path}: {str(e)}")
        
        # Convert bytes to MB for logging
        size_cleaned_mb = size_cleaned / (1024 * 1024)
        
        logger.info(f"Cleanup complete: Removed {file_count} files ({size_cleaned_mb:.2f} MB) from {directory}")
        
        # Record cleanup operation in the dashboard database
        try:
            record_cleanup_operation(directory, file_count, size_cleaned_mb, days)
        except Exception as e:
            logger.warning(f"Failed to record cleanup operation in dashboard: {str(e)}")
            
        return {"files_removed": file_count, "space_freed_mb": size_cleaned_mb}
    except Exception as e:
        logger.error(f"Error during file cleanup in {directory}: {str(e)}")
        return {"files_removed": 0, "space_freed_mb": 0}

async def run_daemon(config_data):
    """
    Run the application in daemon mode, processing channels at regular intervals.
    
    Args:
        config_data (dict): Configuration data
    """
    global shutdown_requested
    
    settings = config_data.get('settings', {})
    run_interval = settings.get('run_interval', 3600)  # Default: 1 hour
    
    last_run_time = 0
    last_deletion_check_time = 0
    deletion_check_interval = 86400  # Check for deleted videos once per day
    
    logger.info(f"Starting daemon mode with run interval of {run_interval} seconds")
    
    # Main daemon loop
    while not shutdown_requested:
        current_time = time.time()
        
        # Check if it's time to run processing
        if current_time - last_run_time >= run_interval:
            logger.info("Running scheduled processing")
            try:
                await process_channels(config_data)
                last_run_time = current_time
            except Exception as e:
                logger.error(f"Error in scheduled processing: {str(e)}", exc_info=True)
        
        # Check if it's time to check for deleted videos
        if current_time - last_deletion_check_time >= deletion_check_interval:
            logger.info("Running scheduled deletion check")
            try:
                await check_deleted_videos()
                last_deletion_check_time = current_time
            except Exception as e:
                logger.error(f"Error in deletion check: {str(e)}", exc_info=True)
        
        # Sleep for a bit to avoid high CPU usage
        sleep_time = min(60, run_interval / 10)  # Sleep for max 1 minute or 1/10 of run interval
        logger.debug(f"Sleeping for {sleep_time} seconds")
        
        # Use a loop with short sleeps to allow for faster shutdown
        for _ in range(int(sleep_time)):
            if shutdown_requested:
                break
            await asyncio.sleep(1)
            
    logger.info("Daemon mode stopped")

async def check_deleted_videos():
    """
    Check all uploaded videos to see if any have been deleted from YouTube.
    This helps keep the dashboard in sync with actual YouTube state.
    """
    try:
        logger.info("Checking for deleted YouTube videos")
        uploader = YouTubeUploader()
        video_history = VideoHistory()
        
        # Get all videos that were successfully uploaded
        uploaded_videos = video_history.get_all_uploaded_videos()
        if not uploaded_videos:
            logger.info("No uploaded videos to check")
            return
            
        logger.info(f"Checking {len(uploaded_videos)} videos for deletion status")
        deleted_count = 0
        
        # Check each video
        for video in uploaded_videos:
            if shutdown_requested:
                logger.info("Shutdown requested, stopping deleted video check")
                break
                
            youtube_id = video.get('youtube_id')
            if not youtube_id:
                continue
                
            # Check if video still exists
            exists = uploader.check_video_exists(youtube_id)
            if not exists:
                deleted_count += 1
                logger.info(f"Video {youtube_id} confirmed as deleted from YouTube")
                
        logger.info(f"Deleted video check completed. Found {deleted_count} deleted videos.")
    
    except Exception as e:
        logger.error(f"Error checking for deleted videos: {str(e)}", exc_info=True)

def load_quota_usage():
    """
    Load the current day's YouTube API quota usage from the log file.
    
    Returns:
        dict: Current quota usage information
    """
    try:
        if os.path.exists(QUOTA_LOG_FILE):
            with open(QUOTA_LOG_FILE, 'r') as f:
                quota_data = json.load(f)
                
            # Check if we have data for today
            today = datetime.now().strftime('%Y-%m-%d')
            if today in quota_data:
                return quota_data
            else:
                # New day, start fresh but keep history
                quota_data[today] = {
                    "used": 0,
                    "operations": {},
                    "remaining": DAILY_QUOTA_LIMIT,
                    "last_updated": datetime.now().isoformat()
                }
                return quota_data
        else:
            # Create new log file with today's entry
            today = datetime.now().strftime('%Y-%m-%d')
            quota_data = {
                today: {
                    "used": 0,
                    "operations": {},
                    "remaining": DAILY_QUOTA_LIMIT,
                    "last_updated": datetime.now().isoformat()
                }
            }
            return quota_data
    except Exception as e:
        logger.error(f"Error loading quota usage data: {str(e)}")
        # Return a default structure
        today = datetime.now().strftime('%Y-%m-%d')
        return {
            today: {
                "used": 0, 
                "operations": {}, 
                "remaining": DAILY_QUOTA_LIMIT,
                "last_updated": datetime.now().isoformat()
            }
        }

def save_quota_usage(quota_data):
    """
    Save the updated quota usage to the log file.
    
    Args:
        quota_data (dict): Quota usage information to save
    """
    try:
        with open(QUOTA_LOG_FILE, 'w') as f:
            json.dump(quota_data, f, indent=2)
        logger.debug("Quota usage data saved")
    except Exception as e:
        logger.error(f"Error saving quota usage data: {str(e)}")

def track_api_usage(operation, count=1):
    """
    Track YouTube API usage for quota monitoring.
    
    Args:
        operation (str): The API operation performed
        count (int): Number of times the operation was performed
    """
    try:
        # Load current usage
        quota_data = load_quota_usage()
        today = datetime.now().strftime('%Y-%m-%d')
        
        # Get cost of operation
        operation_cost = QUOTA_COST.get(operation, 1) * count
        
        # Update usage
        if today not in quota_data:
            quota_data[today] = {
                "used": 0,
                "operations": {},
                "remaining": DAILY_QUOTA_LIMIT,
                "last_updated": datetime.now().isoformat()
            }
            
        # Update operation count
        if operation not in quota_data[today]["operations"]:
            quota_data[today]["operations"][operation] = {"count": 0, "cost": 0}
            
        quota_data[today]["operations"][operation]["count"] += count
        quota_data[today]["operations"][operation]["cost"] += operation_cost
        
        # Update totals
        quota_data[today]["used"] += operation_cost
        quota_data[today]["remaining"] = max(0, DAILY_QUOTA_LIMIT - quota_data[today]["used"])
        quota_data[today]["last_updated"] = datetime.now().isoformat()
        
        # Check if approaching limit
        if quota_data[today]["remaining"] < 1000:
            logger.warning(f"!!! WARNING: YouTube API quota running low: {quota_data[today]['remaining']} units remaining !!!")
        
        # Save updated data
        save_quota_usage(quota_data)
        
        logger.info(f"YouTube API usage tracked: {operation} (+{operation_cost} units), {quota_data[today]['remaining']} remaining")
        return quota_data[today]["remaining"]
    except Exception as e:
        logger.error(f"Error tracking API usage: {str(e)}")
        return None

def check_quota_available(operation, count=1):
    """
    Check if there's enough quota available for an operation.
    
    Args:
        operation (str): The API operation to perform
        count (int): Number of operations planned
        
    Returns:
        bool: True if enough quota is available, False otherwise
    """
    try:
        # Load current usage
        quota_data = load_quota_usage()
        today = datetime.now().strftime('%Y-%m-%d')
        
        # Get cost of operation
        operation_cost = QUOTA_COST.get(operation, 1) * count
        
        # Get remaining quota
        if today in quota_data:
            remaining = quota_data[today].get("remaining", DAILY_QUOTA_LIMIT)
        else:
            remaining = DAILY_QUOTA_LIMIT
            
        # Check if enough quota is available
        if remaining >= operation_cost:
            return True
        else:
            logger.warning(f"Not enough YouTube API quota for {operation} ({operation_cost} units needed, {remaining} available)")
            return False
    except Exception as e:
        logger.error(f"Error checking quota availability: {str(e)}")
        # Default to True to prevent blocking operations due to tracking errors
        return True

async def main():
    """Main entry point for the application."""
    # Parse command line arguments
    parser = argparse.ArgumentParser(description='TikTok to YouTube Shorts Repurposing Tool')
    parser.add_argument('--config', type=str, default='channels.json', 
                        help='Path to the channels configuration file (default: channels.json)')
    parser.add_argument('--group', type=str, 
                        help='Channel group to process (e.g. sports, misc, films) or specify full filename with --config')
    parser.add_argument('--no-uploads', action='store_true',
                       help='Disable uploads even if enabled in config')
    parser.add_argument('--days-to-keep', type=int,
                       help='Override file retention days setting')
    args = parser.parse_args()
    
    # Determine config file based on arguments
    config_file = args.config
    if args.group:
        # Try the new format first (channels-group.json)
        group_config = f'channels-{args.group}.json'
        # If not found, try legacy format (channelsGroup.json)
        legacy_config = f'channels{args.group}.json'
        
        if os.path.exists(group_config):
            config_file = group_config
            logger.info(f"Using channel group {args.group} configuration: {group_config}")
        elif os.path.exists(legacy_config):
            config_file = legacy_config
            logger.info(f"Using legacy channel group {args.group} configuration: {legacy_config}")
        else:
            logger.warning(f"Group config not found for '{args.group}', using default {config_file}")
    
    # Register signal handlers
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    logger.info(f"TikTok to YouTube Shorts Repurposing Tool started with config: {config_file}")
    
    # Start the dashboard in a separate thread
    dashboard_thread = start_dashboard_thread()
    logger.info("Dashboard started")
    
    # Load configuration
    config_data = load_channels_config(config_file)
    
    # Override upload setting if --no-uploads flag is used
    if args.no_uploads and 'settings' in config_data:
        config_data['settings']['upload'] = False
        logger.info("Uploads disabled via command line argument")
    
    # Override file retention setting if specified
    if args.days_to_keep is not None and 'settings' in config_data:
        config_data['settings']['file_retention_days'] = args.days_to_keep
        logger.info(f"File retention period set to {args.days_to_keep} days via command line")
    
    # Process channels once or enter daemon mode
    if config_data.get("settings", {}).get("daemon", True):
        await run_daemon(config_data)
    else:
        await process_channels(config_data)
    
    logger.info("TikTok to YouTube Shorts Repurposing Tool finished")

if __name__ == "__main__":
    # Run the main async function
    loop = asyncio.get_event_loop()
    try:
        loop.run_until_complete(main())
    except KeyboardInterrupt:
        logger.info("Interrupted by user, exiting...")
    finally:
        loop.close() 