"""
Module for uploading videos to YouTube as shorts.
"""
import os
import json
import logging
import random
import time
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List, Tuple, Union
import httplib2
import google.oauth2.credentials
import google_auth_oauthlib.flow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload
from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
import config

logger = logging.getLogger(__name__)

# YouTube API quota costs for various operations
QUOTA_COSTS = {
    'videos.insert': 1600,  # Upload a video
    'videos.list': 1,       # Get video details
    'videos.update': 50,    # Update video metadata
    'playlistItems.insert': 50,  # Add to playlist
    'channels.list': 1      # Get channel info
}

class YouTubeUploader:
    """Handles uploading videos to YouTube as shorts."""
    
    def __init__(self):
        """Initialize the YouTube uploader with API settings."""
        self.client_secrets_file = config.YOUTUBE_CLIENT_SECRETS_FILE
        self.scopes = config.YOUTUBE_SCOPES
        self.api_service_name = config.YOUTUBE_API_SERVICE_NAME
        self.api_version = config.YOUTUBE_API_VERSION
        self.youtube_defaults = config.YOUTUBE_DEFAULTS
        self.reposting_settings = config.REPOSTING_SETTINGS
        self.credentials = None
        self.youtube = None
        self.token_file = "youtube_token.json"
        self.setup_logging()
        self.api = self._authenticate()
        self.quota_log_file = "youtube_api_quota.json"
        self.daily_quota_limit = 10000  # YouTube API daily quota limit
    
    def setup_logging(self):
        """Set up logging for the uploader."""
        logging.basicConfig(
            level=getattr(logging, config.LOGGING['level']),
            format=config.LOGGING['log_format'],
            filename=config.LOGGING['log_file']
        )
    
    def check_token_validity(self) -> Tuple[bool, str]:
        """
        Check if the current token is valid or can be refreshed.
        
        Returns:
            Tuple[bool, str]: (is_valid, message)
        """
        if not self.credentials:
            # Try to load credentials from file
            if os.path.exists(self.token_file):
                try:
                    self.credentials = google.oauth2.credentials.Credentials.from_authorized_user_info(
                        json.loads(open(self.token_file).read())
                    )
                except Exception as e:
                    return False, f"Failed to load credentials: {str(e)}"
            else:
                return False, "No credentials file found"
        
        # Check if credentials are valid
        if self.credentials.valid:
            return True, "Token is valid"
        
        # Check if credentials can be refreshed
        if self.credentials.expired and self.credentials.refresh_token:
            try:
                # Create a Request object for token refresh
                request = Request()
                self.credentials.refresh(request)
                
                # Save refreshed credentials
                self._save_credentials()
                return True, "Token refreshed successfully"
            except RefreshError as e:
                return False, f"Token refresh failed: {str(e)}"
            except Exception as e:
                return False, f"Unexpected error during token refresh: {str(e)}"
        
        return False, "Token is expired and cannot be refreshed"
    
    def _save_credentials(self):
        """Save credentials to file with proper permissions."""
        try:
            with open(self.token_file, 'w') as token:
                token.write(self.credentials.to_json())
            
            # Set proper file permissions if on Unix
            if os.name == 'posix':
                os.chmod(self.token_file, 0o600)
            
            logger.info("Saved credentials to file")
        except Exception as e:
            logger.error(f"Failed to save credentials: {str(e)}")
    
    def _authenticate(self):
        """
        Authenticate with the YouTube API.
        
        Returns:
            googleapiclient.discovery.Resource: Authenticated YouTube API client
        """
        try:
            # First check if we already have valid credentials
            is_valid, message = self.check_token_validity()
            
            if is_valid:
                logger.info(f"Authentication status: {message}")
            else:
                logger.warning(f"Authentication needs renewal: {message}")
                
                # Try to run the OAuth flow
                try:
                    logger.info("Initiating OAuth flow for new credentials")
                    flow = google_auth_oauthlib.flow.InstalledAppFlow.from_client_secrets_file(
                        self.client_secrets_file, self.scopes
                    )
                    self.credentials = flow.run_local_server(port=0)
                    self._save_credentials()
                    logger.info("New credentials obtained successfully")
                except Exception as auth_error:
                    logger.error(f"OAuth flow failed: {str(auth_error)}")
                    return None
            
            # Build the YouTube API client
            self.youtube = build(
                self.api_service_name,
                self.api_version,
                credentials=self.credentials
            )
            
            logger.info("Successfully authenticated with YouTube API")
            return self.youtube
            
        except Exception as e:
            logger.error(f"Authentication error: {str(e)}")
            return None
    
    def prepare_metadata(self, video_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Prepare metadata for a YouTube upload.
        
        Args:
            video_data (Dict[str, Any]): TikTok video data
            
        Returns:
            Dict[str, Any]: YouTube upload metadata
        """
        # Extract video details
        original_title = video_data.get('caption', '').split('\n')[0][:100]
        if not original_title:
            original_title = f"TikTok Video by @{video_data['author']['username']}"
        
        creator = video_data['author']['username']
        original_link = video_data['url']
        
        # Extract hashtags
        caption = video_data.get('caption', '')
        hashtags = [word[1:] for word in caption.split() if word.startswith('#')]
        if not hashtags:
            hashtags = ['trending', 'viral', 'shorts']
        
        # Format title
        title = self.youtube_defaults['title_format'].format(
            original_title=original_title,
            platform='TikTok',
            creator=creator
        )
        
        # Format description
        description = self.youtube_defaults['description_format'].format(
            platform='TikTok',
            creator=creator,
            original_link=original_link,
            tags=' '.join(hashtags[:5])
        )
        
        # Format tags
        tags = self.youtube_defaults['keywords'] + hashtags
        tags = tags[:30]  # YouTube limits tags to 30
        
        return {
            'snippet': {
                'title': title[:100],  # YouTube limits title to 100 characters
                'description': description[:5000],  # YouTube limits description to 5000 characters
                'tags': tags,
                'categoryId': self.youtube_defaults['category']
            },
            'status': {
                'privacyStatus': self.youtube_defaults['privacy_status'],
                'selfDeclaredMadeForKids': self.youtube_defaults['made_for_kids']
            }
        }
    
    def upload_video(self, video_file: str, video_data: Dict[str, Any]) -> Optional[str]:
        """
        Upload a video to YouTube.
        
        Args:
            video_file (str): Path to the video file
            video_data (Dict[str, Any]): Metadata for the video
            
        Returns:
            Optional[str]: YouTube video ID if successful, None otherwise
        """
        try:
            # Check if API is available
            if not self.api:
                logger.error("YouTube API client not available. Authentication may have failed.")
                return None
                
            # Check if quota is available for upload (videos.insert is very expensive)
            if not self.check_quota_available('videos.insert'):
                logger.error("Not enough YouTube API quota available for video upload")
                return None
            
            # Prepare video metadata
            metadata = self.prepare_metadata(video_data)
            
            # Set privacy status
            if self.youtube_defaults['privacy_status']:
                metadata['status'] = {'privacyStatus': self.youtube_defaults['privacy_status']}
            
            # Add shorts category ID (20 for Gaming, 22 for People & Blogs, 23 for Comedy)
            metadata['snippet']['categoryId'] = self.youtube_defaults.get('category_id', '22')
            
            # Log upload attempt
            logger.info(f"Uploading video to YouTube: {os.path.basename(video_file)}")
            
            # Create upload request
            request = self.youtube.videos().insert(
                part=",".join(metadata.keys()),
                body=metadata,
                media_body=MediaFileUpload(video_file, chunksize=-1, resumable=True)
            )
            
            # Upload with progress tracking
            video_id = self._execute_upload_request(request)
            
            if video_id:
                # Track API usage
                self.track_api_usage('videos.insert')
                
                # Add to shorts playlist if configured
                if self.youtube_defaults.get('shorts_playlist_id'):
                    try:
                        if self.check_quota_available('playlistItems.insert'):
                            playlist_id = self.youtube_defaults['shorts_playlist_id']
                            self._add_to_playlist(video_id, playlist_id)
                            self.track_api_usage('playlistItems.insert')
                    except Exception as e:
                        logger.error(f"Failed to add video to shorts playlist: {str(e)}")
                
                logger.info(f"Video uploaded successfully: https://www.youtube.com/watch?v={video_id}")
                return video_id
            else:
                logger.error("Video upload failed: No video ID returned")
                return None
                
        except HttpError as e:
            error_content = json.loads(e.content.decode())
            error_reason = error_content.get('error', {}).get('errors', [{}])[0].get('reason', 'unknown')
            
            logger.error(f"YouTube API error during upload: {error_reason}")
            
            if error_reason == 'quotaExceeded':
                # Track that we've hit the quota limit
                logger.critical("YouTube API quota exceeded! Upload operations will be blocked.")
                
                # Force update quota tracking to show we've used all quota
                today = datetime.now().strftime('%Y-%m-%d')
                quota_data = self._load_quota_usage()
                if today not in quota_data:
                    quota_data[today] = {}
                quota_data[today]['used'] = self.daily_quota_limit
                quota_data[today]['remaining'] = 0
                quota_data[today]['quota_exceeded'] = True
                quota_data[today]['last_updated'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                self._save_quota_usage(quota_data)
            
            return None
            
        except Exception as e:
            logger.error(f"Error during video upload: {str(e)}")
            return None
    
    def get_upload_schedule(self, num_videos: int) -> List[datetime]:
        """
        Generate a schedule for uploading videos.
        
        Args:
            num_videos (int): Number of videos to schedule
            
        Returns:
            List[datetime]: List of scheduled upload times
        """
        now = datetime.now()
        schedule = []
        
        # Get publishing days and times from config
        publish_days = self.reposting_settings['publish_days']
        schedule_times = self.reposting_settings['schedule_times']
        
        day_map = {
            'Monday': 0, 'Tuesday': 1, 'Wednesday': 2, 'Thursday': 3,
            'Friday': 4, 'Saturday': 5, 'Sunday': 6
        }
        
        # Convert publish_days to integers (0 = Monday, 6 = Sunday)
        publish_day_indices = [day_map[day] for day in publish_days if day in day_map]
        if not publish_day_indices:
            publish_day_indices = range(7)  # All days if none specified
        
        # Find the next available day and time
        current_day = now.weekday()
        current_time = now.strftime('%H:%M')
        
        days_added = 0
        while len(schedule) < num_videos:
            # Check if current day is in publish days
            if current_day in publish_day_indices:
                for time_str in schedule_times:
                    # Skip times earlier than current time on the current day
                    if days_added == 0 and time_str <= current_time:
                        continue
                    
                    # Parse the time string
                    hour, minute = map(int, time_str.split(':'))
                    
                    # Create the scheduled time
                    scheduled_time = now + timedelta(days=days_added)
                    scheduled_time = scheduled_time.replace(
                        hour=hour, minute=minute, second=0, microsecond=0
                    )
                    
                    schedule.append(scheduled_time)
                    
                    # Break if we have enough scheduled times
                    if len(schedule) >= num_videos:
                        break
            
            # Move to the next day
            current_day = (current_day + 1) % 7
            days_added += 1
            
            # Reset current time for the new day
            current_time = '00:00'
        
        return schedule
    
    def schedule_uploads(self, video_files: List[str], video_data_list: List[Dict[str, Any]]) -> Dict[str, List[Any]]:
        """
        Schedule uploads for a list of videos.
        
        Args:
            video_files (List[str]): List of paths to video files
            video_data_list (List[Dict[str, Any]]): List of TikTok video data
            
        Returns:
            Dict[str, List[Any]]: Dictionary with scheduled and failed uploads
        """
        # Validate token before proceeding with any uploads
        is_valid, message = self.check_token_validity()
        if not is_valid:
            logger.warning(f"Token validation failed before scheduling uploads: {message}")
            if not self._authenticate():
                logger.error("Failed to authenticate for scheduled uploads")
                return {'scheduled': [], 'failed': [{'status': 'auth_failed', 'message': message}]}
            logger.info("Re-authentication successful for scheduled uploads")
            
        # Check if auto scheduling is enabled
        if not self.reposting_settings['auto_schedule']:
            return self._upload_immediately(video_files, video_data_list)
        
        # Generate upload schedule
        max_videos = min(len(video_files), self.reposting_settings['max_videos_per_day'])
        schedule = self.get_upload_schedule(max_videos)
        
        # Create schedule records
        scheduled = []
        failed = []
        
        for i, (video_file, video_data) in enumerate(zip(video_files[:max_videos], video_data_list[:max_videos])):
            scheduled_time = schedule[i] if i < len(schedule) else datetime.now()
            
            # Schedule the upload
            upload_record = {
                'video_file': video_file,
                'video_data': video_data,
                'scheduled_time': scheduled_time,
                'status': 'scheduled'
            }
            
            scheduled.append(upload_record)
            
            logger.info(f"Scheduled upload for {scheduled_time}: {video_data.get('caption', '')[:50]}")
        
        return {
            'scheduled': scheduled,
            'failed': failed
        }
    
    def _upload_immediately(self, video_files: List[str], video_data_list: List[Dict[str, Any]]) -> Dict[str, List[Any]]:
        """
        Upload multiple videos immediately in sequence.
        
        Args:
            video_files (List[str]): List of video file paths
            video_data_list (List[Dict[str, Any]]): List of corresponding video data
            
        Returns:
            Dict[str, List[Any]]: Results with successful and failed uploads
        """
        results = {
            "successful": [],
            "failed": []
        }
        
        if len(video_files) != len(video_data_list):
            logger.error("Video files and data lists must have the same length")
            return results
        
        # Check total quota required
        total_uploads = len(video_files)
        if not self.check_quota_available('videos.insert', total_uploads):
            # Determine how many videos we can upload with remaining quota
            quota_data = self._load_quota_usage()
            today = datetime.now().strftime('%Y-%m-%d')
            used_quota = quota_data.get(today, {}).get("used", 0)
            remaining_quota = self.daily_quota_limit - used_quota
            
            # Reserve 5% of quota for other operations
            reserve_quota = self.daily_quota_limit * 0.05
            effective_remaining = remaining_quota - reserve_quota
            
            # Calculate how many uploads we can do
            cost_per_upload = QUOTA_COSTS.get('videos.insert', 1600)
            possible_uploads = int(effective_remaining / cost_per_upload)
            
            if possible_uploads <= 0:
                logger.error(f"Not enough YouTube API quota for {total_uploads} uploads")
                
                # Mark all uploads as failed due to quota
                for i, video_data in enumerate(video_data_list):
                    video_title = video_data.get('caption', f"Video {i+1}")
                    results["failed"].append({
                        "file": video_files[i],
                        "title": video_title,
                        "error": "Quota exceeded"
                    })
                return results
            
            logger.warning(f"Limited quota available. Only uploading {possible_uploads}/{total_uploads} videos")
            # Limit uploads to what quota allows
            video_files = video_files[:possible_uploads]
            video_data_list = video_data_list[:possible_uploads]
            
            # Mark remaining videos as failed due to quota
            for i in range(possible_uploads, total_uploads):
                video_title = video_data_list[i].get('caption', f"Video {i+1}")
                results["failed"].append({
                    "file": video_files[i],
                    "title": video_title,
                    "error": "Quota exceeded"
                })
        
        # Process the uploads we can do
        for i, (video_file, video_data) in enumerate(zip(video_files, video_data_list)):
            logger.info(f"Uploading video {i+1}/{len(video_files)}: {video_file}")
            
            upload_result = self.upload_video(video_file, video_data)
            
            if upload_result:
                logger.info(f"Successfully uploaded: {video_file} as {upload_result}")
                results["successful"].append({
                    "file": video_file,
                    "video_id": upload_result,
                    "title": video_data.get('caption', f"Video {i+1}")
                })
                
                # Add a delay between uploads to avoid rate limits
                if i < len(video_files) - 1:
                    delay = random.randint(3, 10)
                    logger.info(f"Waiting {delay} seconds before next upload...")
                    time.sleep(delay)
            else:
                logger.error(f"Failed to upload: {video_file}")
                results["failed"].append({
                    "file": video_file,
                    "title": video_data.get('caption', f"Video {i+1}"),
                    "error": "Upload failed"
                })
        
        return results
    
    def get_youtube_metrics(self, youtube_ids: Union[str, List[str]]) -> Dict[str, Dict[str, Any]]:
        """
        Fetch metrics for YouTube videos.
        
        Args:
            youtube_ids: Either a single YouTube ID or a list of IDs
            
        Returns:
            Dictionary mapping YouTube IDs to their metrics (views, likes, comments)
        """
        if not self.youtube:
            logger.info("No YouTube client available, authenticating...")
            if not self._authenticate():
                logger.error("Failed to authenticate with YouTube API")
                return {}
        
        # Convert single ID to list for consistent processing
        if isinstance(youtube_ids, str):
            youtube_ids = [youtube_ids]
        
        # Initialize result dictionary
        results = {}
        
        # Process in batches of 50 (YouTube API limit)
        for i in range(0, len(youtube_ids), 50):
            batch_ids = youtube_ids[i:i+50]
            
            try:
                # Make the API request
                response = self.youtube.videos().list(
                    part="statistics",
                    id=",".join(batch_ids)
                ).execute()
                
                # Process the results
                for item in response.get("items", []):
                    video_id = item["id"]
                    statistics = item.get("statistics", {})
                    
                    results[video_id] = {
                        "views": int(statistics.get("viewCount", 0)),
                        "likes": int(statistics.get("likeCount", 0)),
                        "comments": int(statistics.get("commentCount", 0)),
                        "favorites": int(statistics.get("favoriteCount", 0)),
                        "last_updated": datetime.now().isoformat()
                    }
                    
                    logger.info(f"Fetched metrics for YouTube video {video_id}: {results[video_id]}")
            
            except HttpError as e:
                logger.error(f"YouTube API error: {str(e)}")
            except Exception as e:
                logger.error(f"Error fetching YouTube metrics: {str(e)}")
        
        return results
    
    def check_video_exists(self, video_id):
        """
        Check if a video still exists on YouTube.
        This is useful for detecting deleted videos.
        
        Args:
            video_id (str): YouTube video ID
            
        Returns:
            bool: True if the video exists, False otherwise
        """
        if not self.youtube:
            logger.error("YouTube API client not available")
            return False
            
        try:
            # Check if we have enough quota
            if not self.check_quota_available('videos.list'):
                logger.warning(f"Skipping video existence check due to quota limits")
                return True  # Assume it exists to avoid false positives
                
            # Request video details
            request = self.youtube.videos().list(
                part="status",
                id=video_id
            )
            response = request.execute()
            
            # Track API usage
            self.track_api_usage('videos.list')
            
            # Check if any items were returned
            if 'items' in response and len(response['items']) > 0:
                return True
            else:
                logger.info(f"Video {video_id} not found on YouTube")
                return False
                
        except HttpError as e:
            if e.resp.status == 404:
                logger.info(f"Video {video_id} not found on YouTube (404)")
                return False
            else:
                logger.error(f"YouTube API error checking video {video_id}: {str(e)}")
                return False
        except Exception as e:
            logger.error(f"Error checking if video exists: {str(e)}")
            return False
    
    def _load_quota_usage(self) -> Dict[str, Any]:
        """
        Load YouTube API quota usage data from file.
        
        Returns:
            Dict[str, Any]: Dictionary of quota usage data by date
        """
        try:
            if os.path.exists(self.quota_log_file):
                with open(self.quota_log_file, 'r') as f:
                    quota_data = json.load(f)
                    logger.debug(f"Loaded quota data: {quota_data}")
                    return quota_data
        except Exception as e:
            logger.error(f"Failed to load quota data: {str(e)}")
        
        # Return empty quota data if file doesn't exist or couldn't be loaded
        return {}
    
    def _save_quota_usage(self, quota_data: Dict[str, Any]) -> bool:
        """
        Save YouTube API quota usage data to file.
        
        Args:
            quota_data (Dict[str, Any]): Quota usage data to save
            
        Returns:
            bool: True if saved successfully, False otherwise
        """
        try:
            with open(self.quota_log_file, 'w') as f:
                json.dump(quota_data, f, indent=2)
            
            # Set proper file permissions if on Unix
            if os.name == 'posix':
                os.chmod(self.quota_log_file, 0o644)
                
            logger.debug(f"Saved quota data: {quota_data}")
            return True
        except Exception as e:
            logger.error(f"Failed to save quota data: {str(e)}")
            return False
    
    def track_api_usage(self, operation: str, count: int = 1) -> bool:
        """
        Track YouTube API operation for quota management.
        
        Args:
            operation (str): API operation name (e.g., 'videos.insert')
            count (int): Number of operations performed
            
        Returns:
            bool: True if tracking succeeded, False otherwise
        """
        try:
            # Get operation cost
            cost_per_op = QUOTA_COSTS.get(operation, 1)
            total_cost = cost_per_op * count
            
            # Get current date
            today = datetime.now().strftime('%Y-%m-%d')
            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            
            # Load existing quota data
            quota_data = self._load_quota_usage()
            
            # Initialize today's entry if it doesn't exist
            if today not in quota_data:
                quota_data[today] = {
                    "used": 0,
                    "remaining": self.daily_quota_limit,
                    "last_updated": timestamp,
                    "operations": {}
                }
            
            # Update usage data
            quota_data[today]["used"] += total_cost
            quota_data[today]["remaining"] = max(0, self.daily_quota_limit - quota_data[today]["used"])
            quota_data[today]["last_updated"] = timestamp
            
            # Add or update operation-specific data
            if operation not in quota_data[today]["operations"]:
                quota_data[today]["operations"][operation] = {
                    "count": 0,
                    "cost": 0
                }
            
            quota_data[today]["operations"][operation]["count"] += count
            quota_data[today]["operations"][operation]["cost"] += total_cost
            
            # Save updated data
            self._save_quota_usage(quota_data)
            
            # Log the quota usage
            logger.info(f"API Quota: Used {total_cost} units for {operation} ({count} calls). " +
                        f"Total: {quota_data[today]['used']}/{self.daily_quota_limit}, " +
                        f"Remaining: {quota_data[today]['remaining']}")
            
            return True
        
        except Exception as e:
            logger.error(f"Failed to track API usage: {str(e)}")
            return False
    
    def check_quota_available(self, operation: str, count: int = 1) -> bool:
        """
        Check if sufficient quota is available for an operation.
        
        Args:
            operation (str): API operation name (e.g., 'videos.insert')
            count (int): Number of operations to check
            
        Returns:
            bool: True if sufficient quota is available, False otherwise
        """
        try:
            # Get operation cost
            cost_per_op = QUOTA_COSTS.get(operation, 1)
            total_cost = cost_per_op * count
            
            # Get current date
            today = datetime.now().strftime('%Y-%m-%d')
            
            # Load existing quota data
            quota_data = self._load_quota_usage()
            
            # Calculate available quota
            used_quota = 0
            if today in quota_data:
                used_quota = quota_data[today].get("used", 0)
            
            remaining_quota = self.daily_quota_limit - used_quota
            
            # For videos.insert operations, allow using up to 95% of remaining quota
            # This ensures we can still perform other operations like list and get
            if operation == 'videos.insert':
                # Reserve 5% of daily quota for other operations
                reserve_quota = self.daily_quota_limit * 0.05
                effective_remaining = remaining_quota - reserve_quota
                
                if total_cost > effective_remaining:
                    # If we can't upload all videos, try to upload as many as possible
                    possible_uploads = int(effective_remaining / cost_per_op)
                    if possible_uploads > 0:
                        logger.warning(f"Can only upload {possible_uploads}/{count} videos with remaining quota. " +
                                      f"Remaining: {remaining_quota}/{self.daily_quota_limit}")
                        # If we can upload at least one video, return True and let the caller handle the count
                        return True
                    else:
                        logger.warning(f"Quota limit would be exceeded by {operation} ({total_cost} units). " +
                                      f"Remaining: {remaining_quota}/{self.daily_quota_limit}")
                        return False
            else:
                # Check if operation would exceed quota
                if total_cost > remaining_quota:
                    logger.warning(f"Quota limit would be exceeded by {operation} ({total_cost} units). " +
                                  f"Remaining: {remaining_quota}/{self.daily_quota_limit}")
                    return False
            
            logger.debug(f"Sufficient quota available for {operation} ({total_cost} units). " +
                        f"Remaining: {remaining_quota}/{self.daily_quota_limit}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to check quota availability: {str(e)}")
            # Conservative approach: if we can't check quota, assume we don't have enough
            return False
    
    def get_quota_summary(self) -> Dict[str, Any]:
        """
        Get a summary of quota usage for today and recent history.
        
        Returns:
            Dict[str, Any]: Summary of quota usage
        """
        try:
            # Load quota data
            quota_data = self._load_quota_usage()
            
            # Get current date
            today = datetime.now().strftime('%Y-%m-%d')
            
            # Get today's usage
            today_usage = quota_data.get(today, {
                "used": 0,
                "remaining": self.daily_quota_limit,
                "last_updated": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                "operations": {}
            })
            
            # Get historical data (last 7 days)
            historical_data = {}
            for i in range(1, 8):
                past_date = (datetime.now() - timedelta(days=i)).strftime('%Y-%m-%d')
                if past_date in quota_data:
                    historical_data[past_date] = quota_data[past_date]
            
            # Create summary
            summary = {
                "today": today_usage,
                "history": historical_data,
                "daily_limit": self.daily_quota_limit,
                "percent_used": round((today_usage["used"] / self.daily_quota_limit) * 100, 2)
            }
            
            # Add warning if quota is running low
            if summary["percent_used"] > 80:
                summary["warning"] = f"Quota usage is high ({summary['percent_used']}%)! Consider limiting operations."
            
            return summary
            
        except Exception as e:
            logger.error(f"Failed to get quota summary: {str(e)}")
            return {
                "today": {
                    "used": 0,
                    "remaining": self.daily_quota_limit,
                    "operations": {}
                },
                "history": {},
                "daily_limit": self.daily_quota_limit,
                "percent_used": 0,
                "error": str(e)
            }
    
    def _execute_upload_request(self, request) -> Optional[str]:
        """
        Execute a YouTube API upload request with progress tracking.
        
        Args:
            request: The YouTube API request object
            
        Returns:
            Optional[str]: Video ID if successful, None otherwise
        """
        try:
            response = None
            retries = 0
            max_retries = 3
            
            # Execute upload with progress tracking
            while response is None and retries < max_retries:
                try:
                    status, response = request.next_chunk()
                    if status:
                        progress = int(status.progress() * 100)
                        logger.info(f"Upload progress: {progress}%")
                except HttpError as e:
                    error = json.loads(e.content.decode('utf-8'))
                    if error.get('error', {}).get('code') in [401, 403]:
                        logger.warning("Authentication error during upload, attempting to refresh token")
                        if not self._authenticate():
                            logger.error("Failed to re-authenticate during upload")
                            return None
                        
                        # Retry the upload
                        retries += 1
                        if retries < max_retries:
                            logger.info(f"Retrying upload (attempt {retries+1}/{max_retries})...")
                            time.sleep(2)  # Wait a moment before retrying
                        else:
                            logger.error("Maximum retries reached, upload failed")
                            return None
                    else:
                        # Other API errors
                        raise
            
            if response and 'id' in response:
                video_id = response['id']
                logger.info(f"Upload complete. Video ID: {video_id}")
                return video_id
            else:
                logger.error("Upload failed: No valid response received")
                return None
                
        except Exception as e:
            logger.error(f"Error during upload execution: {str(e)}")
            return None
    
    def _add_to_playlist(self, video_id: str, playlist_id: str) -> bool:
        """
        Add a video to a YouTube playlist.
        
        Args:
            video_id (str): YouTube video ID
            playlist_id (str): YouTube playlist ID
            
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            logger.info(f"Adding video {video_id} to playlist {playlist_id}")
            
            # Create the request
            request = self.youtube.playlistItems().insert(
                part="snippet",
                body={
                    "snippet": {
                        "playlistId": playlist_id,
                        "resourceId": {
                            "kind": "youtube#video",
                            "videoId": video_id
                        }
                    }
                }
            )
            
            # Execute the request
            response = request.execute()
            
            if response and 'id' in response:
                logger.info(f"Video added to playlist successfully")
                return True
            else:
                logger.warning("Failed to add video to playlist: No valid response")
                return False
                
        except HttpError as e:
            error_content = json.loads(e.content.decode())
            error_reason = error_content.get('error', {}).get('errors', [{}])[0].get('reason', 'unknown')
            logger.error(f"YouTube API error adding to playlist: {error_reason}")
            return False
            
        except Exception as e:
            logger.error(f"Error adding video to playlist: {str(e)}")
            return False 