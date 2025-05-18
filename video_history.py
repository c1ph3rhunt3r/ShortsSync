"""
Module for tracking video upload history to prevent duplicate uploads.
"""
import os
import json
import logging
from typing import List, Dict, Any, Optional
from datetime import datetime

logger = logging.getLogger(__name__)

class VideoHistory:
    """Keeps track of videos that have been processed and uploaded."""
    
    def __init__(self, history_file: str = "data/video_history.json"):
        """
        Initialize the video history tracker.
        
        Args:
            history_file (str): Path to the history file
        """
        self.history_file = history_file
        self.history = self._load_history()
        
    def _load_history(self) -> Dict[str, List[Dict[str, Any]]]:
        """
        Load video history from file.
        
        Returns:
            Dict[str, List[Dict[str, Any]]]: Dictionary with channel usernames as keys and lists of video IDs as values
        """
        try:
            # Create directory if it doesn't exist
            os.makedirs(os.path.dirname(self.history_file), exist_ok=True)
            
            # Check if history file exists
            if not os.path.exists(self.history_file):
                # Create empty history file
                empty_history = {}
                with open(self.history_file, 'w') as f:
                    json.dump(empty_history, f, indent=2)
                return empty_history
            
            # Load history from file
            with open(self.history_file, 'r') as f:
                history = json.load(f)
            
            logger.info(f"Loaded video history for {len(history)} channels")
            return history
            
        except Exception as e:
            logger.error(f"Error loading video history: {str(e)}")
            return {}
    
    def _save_history(self) -> bool:
        """
        Save video history to file.
        
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            # Create directory if it doesn't exist
            os.makedirs(os.path.dirname(self.history_file), exist_ok=True)
            
            # Save history to file
            with open(self.history_file, 'w') as f:
                json.dump(self.history, f, indent=2, default=str)
            
            logger.info(f"Saved video history for {len(self.history)} channels")
            return True
            
        except Exception as e:
            logger.error(f"Error saving video history: {str(e)}")
            return False
    
    def is_video_uploaded(self, username: str, video_id: str) -> bool:
        """
        Check if a video has already been uploaded.
        
        Args:
            username (str): TikTok username
            video_id (str): TikTok video ID
            
        Returns:
            bool: True if the video has been uploaded, False otherwise
        """
        # Clean username (remove @ if present)
        if username.startswith('@'):
            username = username[1:]
        
        # Check if channel exists in history
        if username not in self.history:
            return False
        
        # Check if video ID exists in channel history
        for video in self.history[username]:
            if video['video_id'] == video_id:
                return True
        
        return False
    
    def filter_new_videos(self, username: str, videos: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Filter out videos that have already been uploaded.
        
        Args:
            username (str): TikTok username
            videos (List[Dict[str, Any]]): List of video data dictionaries
            
        Returns:
            List[Dict[str, Any]]: List of videos that haven't been uploaded yet
        """
        # Clean username (remove @ if present)
        if username.startswith('@'):
            username = username[1:]
        
        new_videos = []
        
        for video in videos:
            if not self.is_video_uploaded(username, video['id']):
                new_videos.append(video)
        
        logger.info(f"Filtered {len(videos) - len(new_videos)} previously uploaded videos for @{username}")
        return new_videos
    
    def mark_video_uploaded(self, username: str, video_data: Dict[str, Any], youtube_id: Optional[str] = None) -> bool:
        """
        Mark a video as uploaded.
        
        Args:
            username (str): TikTok username
            video_data (Dict[str, Any]): Video data dictionary
            youtube_id (Optional[str]): YouTube video ID if available
            
        Returns:
            bool: True if successful, False otherwise
        """
        # Clean username (remove @ if present)
        if username.startswith('@'):
            username = username[1:]
        
        try:
            # Create channel in history if it doesn't exist
            if username not in self.history:
                self.history[username] = []
            
            # Add video to history
            self.history[username].append({
                'video_id': video_data['id'],
                'title': video_data.get('caption', '')[:100],
                'upload_date': datetime.now().isoformat(),
                'youtube_id': youtube_id,
                'metrics': {
                    'views': video_data.get('views', 0),
                    'likes': video_data.get('likes', 0),
                    'comments': video_data.get('comments', 0),
                    'shares': video_data.get('shares', 0)
                }
            })
            
            # Save history
            return self._save_history()
            
        except Exception as e:
            logger.error(f"Error marking video as uploaded: {str(e)}")
            return False
    
    def mark_videos_uploaded(self, username: str, videos: List[Dict[str, Any]], youtube_ids: Optional[List[str]] = None) -> bool:
        """
        Mark multiple videos as uploaded.
        
        Args:
            username (str): TikTok username
            videos (List[Dict[str, Any]]): List of video data dictionaries
            youtube_ids (Optional[List[str]]): List of YouTube video IDs if available
            
        Returns:
            bool: True if successful, False otherwise
        """
        # Clean username (remove @ if present)
        if username.startswith('@'):
            username = username[1:]
        
        try:
            success = True
            
            for i, video in enumerate(videos):
                youtube_id = youtube_ids[i] if youtube_ids and i < len(youtube_ids) else None
                if not self.mark_video_uploaded(username, video, youtube_id):
                    success = False
            
            return success
            
        except Exception as e:
            logger.error(f"Error marking videos as uploaded: {str(e)}")
            return False
    
    def get_channel_history(self, username: str) -> List[Dict[str, Any]]:
        """
        Get history for a channel.
        
        Args:
            username (str): TikTok username
            
        Returns:
            List[Dict[str, Any]]: List of video histories for the channel
        """
        # Clean username (remove @ if present)
        if username.startswith('@'):
            username = username[1:]
        
        # Return channel history if it exists
        return self.history.get(username, [])
    
    def get_upload_count(self, username: str) -> int:
        """
        Get the number of videos uploaded for a channel.
        
        Args:
            username (str): TikTok username
            
        Returns:
            int: Number of videos uploaded
        """
        # Clean username (remove @ if present)
        if username.startswith('@'):
            username = username[1:]
        
        # Return channel upload count if it exists
        return len(self.history.get(username, []))
    
    def get_all_uploaded_videos(self):
        """
        Get all videos that were successfully uploaded to YouTube.
        Used for checking deleted videos.
        
        Returns:
            List[Dict]: List of uploaded videos with video_id and youtube_id
        """
        try:
            all_videos = []
            
            # Loop through each channel in history
            for channel, history in self.history.items():
                if not isinstance(history, list):
                    # Skip if not a list of videos
                    continue
                    
                # Add videos that have youtube_id (were uploaded)
                for video in history:
                    if not isinstance(video, dict):
                        continue
                        
                    if video.get('youtube_id') and video.get('video_id'):
                        all_videos.append({
                            'channel': channel,
                            'video_id': video.get('video_id'),
                            'youtube_id': video.get('youtube_id'),
                            'title': video.get('title', 'Unknown Title')
                        })
            
            return all_videos
            
        except Exception as e:
            logger.error(f"Error getting all uploaded videos: {str(e)}")
            return [] 