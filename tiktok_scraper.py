"""
Module for scraping TikTok content from specified channels.
"""
import os
import logging
import requests
import random
import time
import json
import yt_dlp
from typing import List, Dict, Any, Optional
from bs4 import BeautifulSoup
import config

logger = logging.getLogger(__name__)

class TikTokScraper:
    """Handles the scraping of TikTok content from specified channels using unofficial methods."""
    
    def __init__(self):
        """Initialize the TikTok scraper."""
        self.proxy = None
        self.user_agents = [
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:89.0) Gecko/20100101 Firefox/89.0',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:89.0) Gecko/20100101 Firefox/89.0'
        ]
        
        if config.PROXY_SETTINGS['use_proxy'] and config.PROXY_SETTINGS['proxy_url']:
            self.proxy = config.PROXY_SETTINGS['proxy_url']
        
        self.setup_logging()
        self.setup_ytdlp()
    
    def setup_logging(self):
        """Set up logging for the scraper."""
        logging.basicConfig(
            level=getattr(logging, config.LOGGING['level']),
            format=config.LOGGING['log_format'],
            filename=config.LOGGING['log_file']
        )
    
    def setup_ytdlp(self):
        """Set up yt-dlp options."""
        self.ytdlp_options = {
            'quiet': True,
            'no_warnings': True,
            'restrictfilenames': True,
            'nooverwrites': True,
            'format': 'best[ext=mp4]',
            'logger': logger,
        }
        
        # Add proxy if configured
        if self.proxy:
            self.ytdlp_options['proxy'] = self.proxy
    
    def _get_headers(self):
        """Get randomized user agent headers to avoid detection."""
        return {
            'User-Agent': random.choice(self.user_agents),
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.5',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Pragma': 'no-cache',
            'Cache-Control': 'no-cache',
        }
    
    async def get_channel_videos(self, username: str, limit: int = 50) -> List[Dict[str, Any]]:
        """
        Get videos from a TikTok channel using unofficial methods.
        
        Args:
            username (str): TikTok username (with or without @)
            limit (int): Maximum number of videos to retrieve
            
        Returns:
            List[Dict[str, Any]]: List of video data dictionaries
        """
        # Clean username (remove @ if present)
        if username.startswith('@'):
            username = username[1:]
        
        logger.info(f"Fetching up to {limit} videos from TikTok user: @{username}")
        
        # Try the yt-dlp method first as it's most reliable
        videos = self._scrape_videos_yt_dlp(username, limit)
        
        if videos:
            logger.info(f"Successfully retrieved {len(videos)} videos using yt-dlp")
            return videos
        
        # If yt-dlp fails, try the other methods
        try:
            # Method 1: Use TikTok Web Scraping
            return await self._scrape_videos_method1(username, limit)
        except Exception as e:
            logger.error(f"Error using method 1 for @{username}: {str(e)}")
            
            try:
                # Method 2: Alternative approach
                return await self._scrape_videos_method2(username, limit)
            except Exception as e:
                logger.error(f"Error using method 2 for @{username}: {str(e)}")
                
                try:
                    # Method 3: Another fallback
                    return self._scrape_videos_method3(username, limit)
                except Exception as e:
                    logger.error(f"All scraping methods failed for @{username}: {str(e)}")
                    return []
    
    def _scrape_videos_yt_dlp(self, username: str, limit: int) -> List[Dict[str, Any]]:
        """
        Scrape videos using yt-dlp, which is the most reliable method.
        
        Args:
            username (str): TikTok username
            limit (int): Maximum number of videos to retrieve
            
        Returns:
            List[Dict[str, Any]]: List of video data dictionaries
        """
        videos = []
        url = f"https://www.tiktok.com/@{username}"
        
        try:
            logger.info(f"Using yt-dlp to scrape videos from @{username}")
            
            ydl_opts = {
                'quiet': True,
                'no_warnings': True,
                'extract_flat': True,
                'dump_single_json': True,
                'simulate': True,
                'skip_download': True,
                'playlistend': limit
            }
            
            # Add proxy if configured
            if self.proxy:
                ydl_opts['proxy'] = self.proxy
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                result = ydl.extract_info(url, download=False)
                
                if 'entries' in result and result['entries']:
                    entries = result['entries']
                    
                    # Process each video entry
                    for entry in entries:
                        # Extract video ID from URL if available
                        video_id = entry.get('id', '')
                        if not video_id and 'url' in entry:
                            # Try to extract ID from URL
                            url_parts = entry['url'].split('/')
                            if len(url_parts) > 0:
                                video_id = url_parts[-1]
                        
                        # Get more detailed information about the video
                        try:
                            video_url = f"https://www.tiktok.com/@{username}/video/{video_id}"
                            video_info = ydl.extract_info(video_url, download=False)
                            
                            # Use detailed info if available, otherwise use entry data
                            if video_info:
                                # Extract view count and other metrics
                                likes = video_info.get('like_count', 0)
                                comments = video_info.get('comment_count', 0)
                                views = video_info.get('view_count', 0)
                                shares = video_info.get('repost_count', 0) 
                                
                                # Create video data dictionary
                                video_data = {
                                    'id': video_id,
                                    'url': video_url,
                                    'created_time': video_info.get('timestamp', 0),
                                    'caption': video_info.get('title', ''),
                                    'likes': likes,
                                    'comments': comments,
                                    'shares': shares,
                                    'views': views,
                                    'duration': video_info.get('duration', 0),
                                    'width': video_info.get('width', 0),
                                    'height': video_info.get('height', 0),
                                    'download_url': video_info.get('url', ''),
                                    'thumbnail_url': video_info.get('thumbnail', ''),
                                    'author': {
                                        'username': username,
                                        'display_name': video_info.get('uploader', username),
                                        'avatar_url': video_info.get('uploader_url', '')
                                    }
                                }
                                
                                # Apply initial content filters
                                if self._passes_initial_filters(video_data):
                                    videos.append(video_data)
                                    
                                # Add delay to avoid rate limiting
                                time.sleep(random.uniform(0.5, 1.5))
                        except Exception as e:
                            logger.warning(f"Error getting detailed info for video {video_id}: {str(e)}")
                    
                    logger.info(f"yt-dlp method: Retrieved {len(videos)} videos from @{username}")
                    return videos
                else:
                    logger.warning(f"yt-dlp method: No entries found for @{username}")
                    return []
                
        except Exception as e:
            logger.error(f"Error using yt-dlp to scrape @{username}: {str(e)}")
            return []
    
    async def _scrape_videos_method1(self, username: str, limit: int) -> List[Dict[str, Any]]:
        """
        Scrape videos using the first method (TikTok web page scraping).
        """
        videos = []
        url = f"https://www.tiktok.com/@{username}"
        
        # Use requests to get the page content
        response = requests.get(url, headers=self._get_headers(), proxies={'http': self.proxy, 'https': self.proxy} if self.proxy else None)
        
        if response.status_code != 200:
            logger.warning(f"Failed to access TikTok page for @{username}, status code: {response.status_code}")
            return videos
        
        # Parse the page with BeautifulSoup
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Look for JSON data in scripts
        for script in soup.find_all('script'):
            if script.string and 'SIGI_STATE' in script.string:
                # Extract JSON data
                json_str = script.string.split('window[\'SIGI_STATE\'] = ')[1].split(';window[\'SIGI_RETRY\']')[0]
                data = json.loads(json_str)
                
                # Extract videos from the data
                items = []
                
                # Navigate through the complex JSON structure
                try:
                    # The structure might change, this is based on observations
                    if 'ItemModule' in data:
                        items = list(data['ItemModule'].values())
                    elif 'ItemList' in data and 'items' in data['ItemList']:
                        items_ids = data['ItemList']['items']
                        items = [data['ItemModule'][item_id] for item_id in items_ids if item_id in data['ItemModule']]
                except Exception as e:
                    logger.error(f"Error parsing JSON data: {str(e)}")
                    continue
                
                # Process up to the limit
                count = 0
                for item in items:
                    if count >= limit:
                        break
                    
                    try:
                        video_data = {
                            'id': item.get('id'),
                            'url': f"https://www.tiktok.com/@{username}/video/{item.get('id')}",
                            'created_time': item.get('createTime'),
                            'caption': item.get('desc', ''),
                            'likes': int(item.get('stats', {}).get('diggCount', 0)),
                            'comments': int(item.get('stats', {}).get('commentCount', 0)),
                            'shares': int(item.get('stats', {}).get('shareCount', 0)),
                            'views': int(item.get('stats', {}).get('playCount', 0)),
                            'duration': float(item.get('video', {}).get('duration', 0)),
                            'width': int(item.get('video', {}).get('width', 0)),
                            'height': int(item.get('video', {}).get('height', 0)),
                            'download_url': item.get('video', {}).get('downloadAddr', '') or 
                                          item.get('video', {}).get('playAddr', ''),
                            'thumbnail_url': item.get('video', {}).get('cover', '') or 
                                           item.get('video', {}).get('originCover', ''),
                            'author': {
                                'username': username,
                                'display_name': item.get('author', {}).get('nickname', username),
                                'avatar_url': item.get('author', {}).get('avatarLarger', '')
                            }
                        }
                        
                        # Apply initial content filters
                        if self._passes_initial_filters(video_data):
                            videos.append(video_data)
                            count += 1
                    except Exception as e:
                        logger.error(f"Error processing video item: {str(e)}")
                
                break
        
        logger.info(f"Method 1: Retrieved {len(videos)} videos from @{username}")
        return videos
    
    async def _scrape_videos_method2(self, username: str, limit: int) -> List[Dict[str, Any]]:
        """
        Scrape videos using the second method (TikTok API emulation).
        """
        videos = []
        # Use the unofficial API endpoint
        url = f"https://www.tiktok.com/node/share/user/@{username}"
        
        params = {
            'count': min(limit, 30),  # API usually limits to 30 per request
            'cursor': 0,
        }
        
        while len(videos) < limit:
            try:
                response = requests.get(
                    url, 
                    params=params, 
                    headers=self._get_headers(),
                    proxies={'http': self.proxy, 'https': self.proxy} if self.proxy else None
                )
                
                if response.status_code != 200:
                    break
                
                data = response.json()
                
                if not data.get('body', {}).get('itemList'):
                    break
                
                items = data['body']['itemList']
                
                for item in items:
                    video_data = {
                        'id': item.get('id'),
                        'url': f"https://www.tiktok.com/@{username}/video/{item.get('id')}",
                        'created_time': item.get('createTime'),
                        'caption': item.get('desc', ''),
                        'likes': int(item.get('stats', {}).get('diggCount', 0)),
                        'comments': int(item.get('stats', {}).get('commentCount', 0)),
                        'shares': int(item.get('stats', {}).get('shareCount', 0)),
                        'views': int(item.get('stats', {}).get('playCount', 0)),
                        'duration': float(item.get('video', {}).get('duration', 0)),
                        'width': int(item.get('video', {}).get('width', 0)),
                        'height': int(item.get('video', {}).get('height', 0)),
                        'download_url': item.get('video', {}).get('downloadAddr', '') or 
                                      item.get('video', {}).get('playAddr', ''),
                        'thumbnail_url': item.get('video', {}).get('cover', '') or 
                                       item.get('video', {}).get('dynamicCover', ''),
                        'author': {
                            'username': username,
                            'display_name': item.get('author', {}).get('nickname', username),
                            'avatar_url': item.get('author', {}).get('avatarLarger', '')
                        }
                    }
                    
                    # Apply initial content filters
                    if self._passes_initial_filters(video_data):
                        videos.append(video_data)
                    
                    if len(videos) >= limit:
                        break
                
                # Get next page cursor
                if 'hasMore' in data['body'] and data['body']['hasMore'] and 'cursor' in data['body']:
                    params['cursor'] = data['body']['cursor']
                else:
                    break
                
                # Sleep to avoid rate limiting
                time.sleep(random.uniform(1.0, 3.0))
                
            except Exception as e:
                logger.error(f"Error in method 2: {str(e)}")
                break
        
        logger.info(f"Method 2: Retrieved {len(videos)} videos from @{username}")
        return videos
    
    def _scrape_videos_method3(self, username: str, limit: int) -> List[Dict[str, Any]]:
        """
        Scrape videos using third method (using external APIs or services).
        This is a fallback method that could use external services or APIs.
        """
        videos = []
        logger.info(f"Using method 3 for @{username}")
        
        # This is where you could integrate with third-party APIs or services
        # For example, services like Rapid API's TikTok API
        # This is just a placeholder - you would need to implement the actual API call
        
        # For demonstration, we'll just create dummy data
        logger.warning(f"Method 3 is a placeholder. No videos retrieved from @{username}")
        
        return videos
    
    def _passes_initial_filters(self, video_data: Dict[str, Any]) -> bool:
        """
        Check if a video passes the initial content filters.
        
        Args:
            video_data (Dict[str, Any]): Video data dictionary
            
        Returns:
            bool: True if video passes initial filters, False otherwise
        """
        filters = config.CONTENT_FILTERS
        
        try:
            # Check minimum metrics with safe defaults
            views = video_data.get('views', 0)
            likes = video_data.get('likes', 0)
            shares = video_data.get('shares', 0)
            duration = video_data.get('duration', 0)
            
            # Check if we have the minimum required data
            if views < filters.get('min_views', 10000):
                return False
                
            # Only check likes if the data exists and filter is set
            if 'min_likes' in filters and filters['min_likes'] > 0 and likes > 0:
                if likes < filters['min_likes']:
                    return False
            
            # Only check shares if the data exists and filter is set
            if 'min_shares' in filters and filters['min_shares'] > 0 and shares > 0:
                if shares < filters['min_shares']:
                    return False
            
            # Check duration constraints
            if duration < filters.get('min_duration', 3):
                return False
            if duration > filters.get('max_duration', 60):
                return False
            
            # Check for excluded hashtags
            caption = video_data.get('caption', '').lower()
            for hashtag in filters.get('exclude_hashtags', []):
                if hashtag.lower() in caption:
                    return False
            
            # Check for required hashtags (if any)
            if filters.get('require_hashtags'):
                found_required = False
                for hashtag in filters['require_hashtags']:
                    if hashtag.lower() in caption:
                        found_required = True
                        break
                if not found_required:
                    return False
            
            # Check for excluded keywords
            for keyword in filters.get('exclude_keywords', []):
                if keyword.lower() in caption:
                    return False
            
            return True
            
        except Exception as e:
            logger.warning(f"Error checking filters for video {video_data.get('id', 'unknown')}: {str(e)}")
            # Default to passing the filter if we can't check due to an error
            # This allows the video to be processed downstream
            return True
    
    async def download_video(self, video_data: Dict[str, Any], output_dir: str = "downloads") -> Optional[str]:
        """
        Download a TikTok video using yt-dlp.
        
        Args:
            video_data (Dict[str, Any]): Video data dictionary
            output_dir (str): Directory to save the downloaded video
            
        Returns:
            Optional[str]: Path to the downloaded video file, or None if download failed
        """
        os.makedirs(output_dir, exist_ok=True)
        
        video_id = video_data['id']
        username = video_data['author']['username']
        output_file = os.path.join(output_dir, f"{username}_{video_id}.mp4")
        
        # Check if file already exists
        if os.path.exists(output_file):
            logger.info(f"Video already downloaded: {output_file}")
            return output_file
        
        try:
            # Configure yt-dlp options for this download
            video_url = video_data['url']
            
            ydl_opts = self.ytdlp_options.copy()
            ydl_opts.update({
                'outtmpl': output_file
            })
            
            logger.info(f"Downloading video from {video_url} using yt-dlp")
            
            # Use yt-dlp to download the video
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([video_url])
            
            # Verify the file was downloaded
            if os.path.exists(output_file):
                logger.info(f"Successfully downloaded video: {output_file}")
                return output_file
            else:
                logger.error(f"Download completed but file not found: {output_file}")
                return None
        
        except Exception as e:
            logger.error(f"Error downloading video {video_id} with yt-dlp: {str(e)}")
            
            # Fallback to legacy method if yt-dlp fails
            try:
                logger.info(f"Falling back to legacy download method for {video_id}")
                return await self._legacy_download_video(video_data, output_dir)
            except Exception as e2:
                logger.error(f"Legacy download also failed for {video_id}: {str(e2)}")
                return None
    
    async def _legacy_download_video(self, video_data: Dict[str, Any], output_dir: str) -> Optional[str]:
        """
        Legacy method to download a TikTok video using direct requests.
        Used as fallback if yt-dlp fails.
        
        Args:
            video_data (Dict[str, Any]): Video data dictionary
            output_dir (str): Directory to save the downloaded video
            
        Returns:
            Optional[str]: Path to the downloaded video file, or None if download failed
        """
        video_id = video_data['id']
        username = video_data['author']['username']
        output_file = os.path.join(output_dir, f"{username}_{video_id}.mp4")
        
        try:
            # Try multiple methods to get the download URL
            download_url = video_data.get('download_url', '')
            
            if not download_url:
                # If no download URL, try to get it from the video page
                logger.info(f"No download URL found, trying to fetch from video page")
                download_url = await self._get_download_url_from_page(video_data['url'])
            
            if not download_url:
                logger.error(f"Could not find download URL for video {video_id}")
                return None
            
            # Download the video with appropriate headers
            response = requests.get(
                download_url, 
                headers=self._get_headers(),
                stream=True,
                proxies={'http': self.proxy, 'https': self.proxy} if self.proxy else None
            )
            
            if response.status_code == 200:
                with open(output_file, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=1024):
                        if chunk:
                            f.write(chunk)
                
                logger.info(f"Downloaded video using legacy method: {output_file}")
                return output_file
            else:
                logger.error(f"Failed to download video {video_id}. Status code: {response.status_code}")
                return None
                
        except Exception as e:
            logger.error(f"Error in legacy download for video {video_id}: {str(e)}")
            return None
    
    async def _get_download_url_from_page(self, video_url: str) -> Optional[str]:
        """
        Extract download URL from the video page.
        
        Args:
            video_url (str): URL of the video page
            
        Returns:
            Optional[str]: Download URL if found, None otherwise
        """
        try:
            response = requests.get(
                video_url, 
                headers=self._get_headers(),
                proxies={'http': self.proxy, 'https': self.proxy} if self.proxy else None
            )
            
            if response.status_code != 200:
                return None
            
            # Parse the page with BeautifulSoup
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # Look for video URLs in the page
            for script in soup.find_all('script'):
                if script.string and 'videoData' in script.string:
                    # Extract JSON data
                    start = script.string.find('{')
                    end = script.string.rfind('}') + 1
                    if start >= 0 and end > start:
                        try:
                            json_str = script.string[start:end]
                            data = json.loads(json_str)
                            
                            # Try to find the video URL in the data
                            if 'itemInfo' in data and 'itemStruct' in data['itemInfo'] and 'video' in data['itemInfo']['itemStruct']:
                                video_data = data['itemInfo']['itemStruct']['video']
                                for key in ['downloadAddr', 'playAddr', 'downloadUrl', 'playUrl']:
                                    if key in video_data and video_data[key]:
                                        return video_data[key]
                        except Exception as e:
                            logger.error(f"Error parsing JSON data from video page: {str(e)}")
            
            # If we couldn't find the URL in scripts, look for video elements
            video_elements = soup.find_all('video')
            for video in video_elements:
                if video.has_attr('src') and video['src']:
                    return video['src']
                
                # Check for source elements inside video
                sources = video.find_all('source')
                for source in sources:
                    if source.has_attr('src') and source['src']:
                        return source['src']
            
            return None
            
        except Exception as e:
            logger.error(f"Error extracting download URL from page: {str(e)}")
            return None 