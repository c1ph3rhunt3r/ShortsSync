"""
Module for analyzing and ranking TikTok content based on performance metrics.
"""
import logging
from typing import List, Dict, Any, Tuple
import pandas as pd
import config
import math

logger = logging.getLogger(__name__)

class ContentAnalyzer:
    """Analyzes and ranks TikTok content based on performance metrics."""
    
    def __init__(self):
        """Initialize the content analyzer with performance metrics from config."""
        self.metrics = config.PERFORMANCE_METRICS
        self.filters = config.CONTENT_FILTERS
        self.setup_logging()
    
    def setup_logging(self):
        """Set up logging for the analyzer."""
        logging.basicConfig(
            level=getattr(logging, config.LOGGING['level']),
            format=config.LOGGING['log_format'],
            filename=config.LOGGING['log_file']
        )
    
    def analyze_videos(self, videos: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Analyze a list of videos and calculate performance scores.
        
        Args:
            videos (List[Dict[str, Any]]): List of video data dictionaries
            
        Returns:
            List[Dict[str, Any]]: List of video data dictionaries with performance scores
        """
        if not videos:
            logger.warning("No videos to analyze")
            return []
        
        # Convert to DataFrame for easier analysis
        df = pd.DataFrame(videos)
        
        # Calculate normalized metrics
        logger.info(f"Analyzing {len(videos)} videos")
        
        # Normalize each metric (scale to 0-1)
        for metric, weight in self.metrics.items():
            if metric in df.columns and len(df) > 1:  # Ensure we have the metric and multiple videos
                # Avoid division by zero by adding a small value
                max_val = df[metric].max() + 0.0001
                df[f'norm_{metric}'] = df[metric] / max_val
            elif metric in df.columns:
                # If only one video, normalize to 1
                df[f'norm_{metric}'] = 1.0
            else:
                logger.warning(f"Metric '{metric}' not found in video data")
                df[f'norm_{metric}'] = 0.0
        
        # Calculate weighted performance score
        df['performance_score'] = 0.0
        for metric, weight in self.metrics.items():
            if f'norm_{metric}' in df.columns:
                df['performance_score'] += df[f'norm_{metric}'] * weight
        
        # Sort by performance score (descending)
        df = df.sort_values('performance_score', ascending=False)
        
        # Convert back to list of dictionaries with score
        result = df.to_dict('records')
        
        logger.info(f"Analyzed {len(result)} videos")
        return result
    
    def select_top_videos(self, videos: List[Dict], channel_name: str, top_n: int = 5) -> List[Dict]:
        """
        Select top performing videos based on engagement score and content policy.
        
        Args:
            videos (List[Dict]): List of video data
            channel_name (str): Channel name for logging and threshold calculation
            top_n (int): Number of top videos to select
            
        Returns:
            List[Dict]: Selected top videos
        """
        if not videos:
            logger.warning(f"Channel {channel_name}: No videos to select from")
            return []
        
        # First apply content policy filters with dynamic thresholds
        filtered_videos = self.filter_by_content_policy(videos, channel_name)
        
        if not filtered_videos:
            logger.warning(f"Channel {channel_name}: All videos filtered out by content policy")
            # If too strict, we could fall back to just duration filtering and newest videos
            try:
                # Filter just by duration for Shorts compatibility
                duration_filtered = []
                for v in videos:
                    try:
                        duration = float(v.get('video', {}).get('duration', 0))
                        if 3 <= duration <= 60:  # Between 3 and 60 seconds for Shorts
                            duration_filtered.append(v)
                    except Exception as e:
                        logger.warning(f"Error checking duration: {str(e)}")
                
                # If we still have videos after basic filtering
                if duration_filtered:
                    # Sort by creation time (newest first) as a fallback
                    filtered_videos = sorted(
                        duration_filtered, 
                        key=lambda x: int(x.get('createTime', 0)), 
                        reverse=True
                    )[:top_n]
                    logger.info(f"Channel {channel_name}: Using duration + recency filter as fallback. Found {len(filtered_videos)} videos.")
                else:
                    # Last resort: just take the newest few videos regardless of duration
                    filtered_videos = sorted(
                        videos, 
                        key=lambda x: int(x.get('createTime', 0)), 
                        reverse=True
                    )[:top_n]
                    logger.info(f"Channel {channel_name}: Using only recency as filter. Found {len(filtered_videos)} videos.")
            except Exception as e:
                logger.warning(f"Error applying fallback filtering: {str(e)}")
                # Absolute last resort: just take the first few videos
                filtered_videos = videos[:top_n]
                logger.info(f"Channel {channel_name}: Using no filtering (last resort). Taking {len(filtered_videos)} videos.")
        
        # Rank videos using our engagement scoring system
        ranked_videos = self.rank_videos(filtered_videos)
        
        # Select the top N videos
        selected = ranked_videos[:min(top_n, len(ranked_videos))]
        
        logger.info(f"Channel {channel_name}: Selected {len(selected)} top videos from {len(videos)} total videos")
        
        # Log selection details with safer extraction of metrics
        for i, video in enumerate(selected):
            try:
                score = video.get('engagement_score', 0)
                stats = video.get('stats', {})
                views = int(stats.get('playCount', 0))
                likes = int(stats.get('diggCount', 0))
                comments = int(stats.get('commentCount', 0))
                
                logger.info(f"Channel {channel_name}: Selected #{i+1}: Score: {score:.2f}, Views: {views}, Likes: {likes}, Comments: {comments}")
            except Exception as e:
                logger.warning(f"Error logging video metrics: {str(e)}")
                logger.info(f"Channel {channel_name}: Selected #{i+1} (metrics unavailable)")
        
        return selected
    
    def get_engagement_rate(self, video: Dict[str, Any]) -> float:
        """
        Calculate the engagement rate for a video.
        
        Engagement rate = (likes + comments + shares) / views
        
        Args:
            video (Dict[str, Any]): Video data dictionary
            
        Returns:
            float: Engagement rate percentage
        """
        views = video.get('views', 0)
        if views == 0:
            return 0.0
            
        likes = video.get('likes', 0)
        comments = video.get('comments', 0)
        shares = video.get('shares', 0)
        
        engagement = (likes + comments + shares) / views * 100
        return round(engagement, 2)
    
    def get_video_statistics(self, videos: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Get statistics for a list of videos.
        
        Args:
            videos (List[Dict[str, Any]]): List of video data dictionaries
            
        Returns:
            Dict[str, Any]: Dictionary of video statistics
        """
        if not videos:
            return {
                'total_videos': 0,
                'avg_views': 0,
                'avg_likes': 0,
                'avg_comments': 0,
                'avg_shares': 0,
                'avg_duration': 0,
                'avg_engagement_rate': 0,
            }
        
        total_videos = len(videos)
        total_views = sum(video.get('views', 0) for video in videos)
        total_likes = sum(video.get('likes', 0) for video in videos)
        total_comments = sum(video.get('comments', 0) for video in videos)
        total_shares = sum(video.get('shares', 0) for video in videos)
        total_duration = sum(video.get('duration', 0) for video in videos)
        
        avg_views = total_views / total_videos
        avg_likes = total_likes / total_videos
        avg_comments = total_comments / total_videos
        avg_shares = total_shares / total_videos
        avg_duration = total_duration / total_videos
        
        # Calculate average engagement rate
        engagement_rates = [self.get_engagement_rate(video) for video in videos]
        avg_engagement_rate = sum(engagement_rates) / total_videos
        
        return {
            'total_videos': total_videos,
            'avg_views': avg_views,
            'avg_likes': avg_likes,
            'avg_comments': avg_comments,
            'avg_shares': avg_shares,
            'avg_duration': avg_duration,
            'avg_engagement_rate': avg_engagement_rate,
        }
    
    def get_hashtags(self, video: Dict[str, Any]) -> List[str]:
        """
        Extract hashtags from video caption.
        
        Args:
            video (Dict[str, Any]): Video data dictionary
            
        Returns:
            List[str]: List of hashtags
        """
        caption = video.get('caption', '')
        words = caption.split()
        hashtags = [word for word in words if word.startswith('#')]
        return hashtags

    def calculate_engagement_score(self, video):
        """
        Calculate an engagement score for a video based on multiple metrics.
        This provides a more well-rounded evaluation of content performance.
        
        Args:
            video (Dict): Video data
            
        Returns:
            float: Engagement score
        """
        # Extract metrics with safety checks
        try:
            views = int(video.get('stats', {}).get('playCount', 0))
            likes = int(video.get('stats', {}).get('diggCount', 0))
            comments = int(video.get('stats', {}).get('commentCount', 0))
            shares = int(video.get('stats', {}).get('shareCount', 0))
            
            # If all metrics are zero, use fallback scoring
            if views == 0 and likes == 0 and comments == 0 and shares == 0:
                # For videos with no metrics, use creation time as a proxy
                # Newer videos first
                try:
                    create_time = int(video.get('createTime', 0))
                    # Scale to a reasonable range (0-5)
                    score = min(5, max(0, (create_time / 1000000000)))
                    logger.info(f"Using fallback scoring for video with no metrics: {score:.2f}")
                    return score
                except:
                    # If create time is also not available, assign a small random score
                    # This ensures some variety in selection rather than always the same videos
                    import random
                    score = random.uniform(0.1, 1.0)
                    logger.info(f"Using random fallback scoring: {score:.2f}")
                    return score
            
            # Avoid division by zero
            if views == 0:
                return 0
            
            # Calculate engagement rate (likes + comments + shares) / views
            engagement_rate = (likes + comments + shares) / views
            
            # Apply logarithmic scaling to views to balance the impact of viral videos
            # This helps prevent overvaluing videos that just got lucky with the algorithm
            log_views = math.log10(views + 1)  # +1 to avoid log(0)
            
            # Weight factors - adjust these based on what's most important for your content
            view_weight = 0.4
            engagement_weight = 0.6
            
            # Calculate final score combining views and engagement
            score = (view_weight * log_views) + (engagement_weight * engagement_rate * 10)
            
            return score
        except Exception as e:
            logger.warning(f"Error calculating engagement score: {str(e)}")
            # Return a default score to avoid breaking the pipeline
            return 0.5

    def rank_videos(self, videos: List[Dict]) -> List[Dict]:
        """
        Rank videos based on metrics and prepare them with rankings.
        
        Args:
            videos (List[Dict]): List of video data
            
        Returns:
            List[Dict]: Ranked video data with scores
        """
        if not videos:
            return []
        
        # For each video, calculate its engagement score
        for video in videos:
            video['engagement_score'] = self.calculate_engagement_score(video)
        
        # Sort videos by their engagement score, highest first
        ranked_videos = sorted(videos, key=lambda x: x.get('engagement_score', 0), reverse=True)
        
        # Set rank and add to description
        for i, video in enumerate(ranked_videos):
            video['rank'] = i + 1
            video['rank_description'] = f"Rank {i+1} of {len(ranked_videos)} videos"
            
        return ranked_videos

    def calculate_dynamic_view_threshold(self, videos: List[Dict], channel_name: str) -> int:
        """
        Calculate a dynamic view threshold based on channel performance.
        Instead of using a fixed threshold, this adapts to each channel's typical performance.
        
        Args:
            videos (List[Dict]): List of videos to analyze
            channel_name (str): Name of the channel
            
        Returns:
            int: Dynamic view threshold for this channel
        """
        if not videos:
            # Fall back to default if no videos to analyze
            return self.filters.get("min_views", 10000)
        
        # Calculate average views for this channel
        try:
            # Extract view counts
            view_counts = [int(video.get('stats', {}).get('playCount', 0)) for video in videos]
            # Filter out zeros to avoid skewing the average
            view_counts = [views for views in view_counts if views > 0]
            
            if not view_counts:
                return self.filters.get("min_views", 10000)
            
            # Sort view counts to calculate percentiles
            view_counts.sort()
            
            # Calculate various statistics
            avg_views = sum(view_counts) / len(view_counts)
            median_views = view_counts[len(view_counts) // 2]
            
            # Calculate 75th percentile of views
            percentile_75_index = int(len(view_counts) * 0.75)
            percentile_75 = view_counts[percentile_75_index]
            
            # Determine channel size category based on average views
            if avg_views < 20000:
                channel_size = "small"
            elif avg_views < 100000:
                channel_size = "medium"
            else:
                channel_size = "large"
            
            # Set threshold based on channel size
            if channel_size == "small":
                # For small channels, set threshold at 70% of average
                dynamic_threshold = int(avg_views * 0.7)
                min_bound = 3000  # Lower minimum for small channels
            elif channel_size == "medium":
                # For medium channels, use the median as baseline
                dynamic_threshold = int(median_views * 0.8)
                min_bound = 8000
            else:
                # For large channels, use 75th percentile as baseline
                dynamic_threshold = int(percentile_75 * 0.7)
                min_bound = 15000
            
            # Set minimum and maximum bounds to prevent extreme values
            max_bound = 500000  # Don't require more than 500K views
            
            threshold = max(min_bound, min(dynamic_threshold, max_bound))
            
            logger.info(f"Calculated dynamic view threshold for channel {channel_name}: {threshold} " +
                       f"(channel size: {channel_size}, average: {int(avg_views)}, median: {int(median_views)})")
            
            return threshold
        except Exception as e:
            logger.error(f"Error calculating dynamic view threshold: {str(e)}")
            # Fall back to default on error
            return self.filters.get("min_views", 10000)

    def filter_by_content_policy(self, videos: List[Dict], channel_name: str) -> List[Dict]:
        """
        Filter videos based on the content policy settings.
        Uses dynamic thresholds based on channel performance.
        
        Args:
            videos (List[Dict]): List of video data
            channel_name (str): Name of the channel for logging
            
        Returns:
            List[Dict]: Filtered list of videos
        """
        if not videos:
            return []
        
        filtered_videos = []
        
        # Calculate dynamic view threshold for this channel
        dynamic_view_threshold = self.calculate_dynamic_view_threshold(videos, channel_name)
        
        for video in videos:
            # Duration checks
            duration = float(video.get('video', {}).get('duration', 0))
            if duration < self.filters.get("min_duration", 0) or duration > self.filters.get("max_duration", 60):
                logger.debug(f"Filtered out video (duration {duration}s): {video.get('desc', 'Unknown')}")
                continue
            
            # View count threshold - using dynamic threshold
            views = int(video.get('stats', {}).get('playCount', 0))
            if views < dynamic_view_threshold:
                logger.debug(f"Filtered out video (only {views} views, below threshold {dynamic_view_threshold}): {video.get('desc', 'Unknown')}")
                continue
            
            # Engagement rate check
            engagement_rate = self.calculate_engagement_score(video)
            if engagement_rate < self.filters.get("min_engagement_rate", 0):
                logger.debug(f"Filtered out video (low engagement {engagement_rate}): {video.get('desc', 'Unknown')}")
                continue
            
            # Check excluded hashtags
            caption = video.get('desc', '')
            excluded_tags = self.filters.get("exclude_hashtags", [])
            if any(tag.lower() in caption.lower() for tag in excluded_tags):
                logger.debug(f"Filtered out video (excluded hashtags): {video.get('desc', 'Unknown')}")
                continue
            
            # Passed all filters
            filtered_videos.append(video)
        
        logger.info(f"Channel {channel_name}: Filtered to {len(filtered_videos)} videos from {len(videos)} based on content policy")
        return filtered_videos 