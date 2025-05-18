"""
Module for processing TikTok videos before uploading to YouTube.
"""
import os
import logging
from typing import Dict, Any, Optional, List
from moviepy.video.io.VideoFileClip import VideoFileClip
from moviepy.video.VideoClip import TextClip
from moviepy.video.compositing.CompositeVideoClip import CompositeVideoClip
import config

logger = logging.getLogger(__name__)

class VideoProcessor:
    """Processes videos for YouTube upload."""
    
    def __init__(self):
        """Initialize the video processor with settings from config."""
        self.reposting_settings = config.REPOSTING_SETTINGS
        self.setup_logging()
    
    def setup_logging(self):
        """Set up logging for the processor."""
        logging.basicConfig(
            level=getattr(logging, config.LOGGING['level']),
            format=config.LOGGING['log_format'],
            filename=config.LOGGING['log_file']
        )
    
    def process_video(self, video_file: str, video_data: Dict[str, Any], output_dir: str = "processed") -> Optional[str]:
        """
        Process a TikTok video for YouTube upload.
        
        Args:
            video_file (str): Path to the video file
            video_data (Dict[str, Any]): Video data dictionary
            output_dir (str): Directory to save the processed video
            
        Returns:
            Optional[str]: Path to the processed video file, or None if processing failed
        """
        if not os.path.exists(video_file):
            logger.error(f"Video file not found: {video_file}")
            return None
        
        # Create output directory if it doesn't exist
        os.makedirs(output_dir, exist_ok=True)
        
        # Generate output filename
        video_id = video_data['id']
        username = video_data['author']['username']
        output_file = os.path.join(output_dir, f"{username}_{video_id}_processed.mp4")
        
        # Check if processed file already exists
        if os.path.exists(output_file):
            logger.info(f"Processed video already exists: {output_file}")
            return output_file
        
        # Track video object for proper cleanup
        video = None
        processed_video = None
        temp_fixed_file = None
        
        try:
            # Load the video
            logger.info(f"Processing video: {video_file}")
            video = VideoFileClip(video_file)
            
            # Check for duration attribute
            if not hasattr(video, 'duration') or video.duration is None or video.duration <= 0:
                logger.error(f"Video has no valid duration attribute")
                # Try to fix by re-encoding to a temporary file
                temp_file = f"{video_file}.temp.mp4"
                try:
                    logger.info(f"Attempting to fix video by re-encoding: {temp_file}")
                    video.write_videofile(
                        temp_file,
                        codec='libx264',
                        audio_codec='aac',
                        preset='ultrafast'
                    )
                    # Close original video and load the fixed one
                    video.close()
                    video = VideoFileClip(temp_file)
                    if not hasattr(video, 'duration') or video.duration is None or video.duration <= 0:
                        raise ValueError("Failed to fix video duration")
                    logger.info(f"Successfully fixed video - new duration: {video.duration:.2f}s")
                except Exception as fix_error:
                    logger.error(f"Failed to fix video: {str(fix_error)}")
                    # Clean up and return None
                    try:
                        video.close()
                    except:
                        pass
                    if os.path.exists(temp_file):
                        try:
                            os.unlink(temp_file)
                        except:
                            pass
                    return None
            
            # Log video properties for debugging
            logger.info(f"Video properties: size={video.size}, fps={video.fps}, duration={video.duration:.2f}s")
            
            # Apply processing based on settings
            processed_video = self._apply_processing(video, video_data)
            
            # Verify processed video has duration set
            if not hasattr(processed_video, 'duration') or processed_video.duration is None or processed_video.duration <= 0:
                logger.info("Setting duration on processed video from original video")
                try:
                    processed_video.duration = video.duration
                except Exception as e:
                    logger.error(f"Could not set duration on processed video: {str(e)}")
                    return None
            
            # Save the processed video
            logger.info(f"Writing processed video to: {output_file}")
            
            # Check if the processed video has audio
            has_audio = hasattr(processed_video, 'audio') and processed_video.audio is not None
            logger.info(f"Processed video has audio: {has_audio}")
            
            # If no audio in processed video but original video has audio, copy it
            if not has_audio and hasattr(video, 'audio') and video.audio is not None:
                logger.info("Copying audio from original video")
                processed_video.audio = video.audio
            
            # Write the video file with explicit audio settings
            processed_video.write_videofile(
                output_file,
                codec='libx264',
                audio_codec='aac',
                temp_audiofile='temp-audio.m4a',
                remove_temp=True,
                ffmpeg_params=['-q:a', '0']  # Use high quality audio
            )
            
            # Close the video clips to release resources
            processed_video.close()
            video.close()
            
            # Clean up temporary file if it exists
            temp_file = f"{video_file}.temp.mp4"
            if os.path.exists(temp_file):
                try:
                    os.unlink(temp_file)
                    logger.info(f"Removed temporary file: {temp_file}")
                except Exception as e:
                    logger.warning(f"Failed to remove temporary file: {str(e)}")
            
            logger.info(f"Video processing complete: {output_file}")
            return output_file
            
        except Exception as e:
            logger.error(f"Error processing video {video_file}: {str(e)}")
            
            # Close video resources
            try:
                if 'video' in locals() and video is not None:
                    video.close()
                if 'processed_video' in locals() and processed_video is not None:
                    processed_video.close()
            except Exception as cleanup_error:
                logger.warning(f"Error during cleanup: {str(cleanup_error)}")
            
            # Clean up temporary file
            temp_file = f"{video_file}.temp.mp4"
            if os.path.exists(temp_file):
                try:
                    os.unlink(temp_file)
                except Exception:
                    pass
            
            return None
    
    def _apply_processing(self, video: VideoFileClip, video_data: Dict[str, Any]) -> VideoFileClip:
        """
        Apply processing to a video.
        
        Args:
            video (VideoFileClip): Video clip to process
            video_data (Dict[str, Any]): Video data dictionary
            
        Returns:
            VideoFileClip: Processed video clip
        """
        processed_video = video
        
        # Process to YouTube Shorts dimensions (9:16 aspect ratio)
        # Calculate current aspect ratio
        current_width, current_height = video.size
        current_ratio = current_width / current_height
        target_ratio = 9/16
        
        # Only crop if the aspect ratio is significantly different
        if abs(current_ratio - target_ratio) > 0.05:
            logger.info(f"Video aspect ratio {current_ratio:.2f} needs adjustment to match 9:16 (0.5625)")
            processed_video = self._crop_to_aspect_ratio(video, 9/16)
        else:
            logger.info(f"Video aspect ratio {current_ratio:.2f} is already close to 9:16 (0.5625), keeping original dimensions")
        
        # Add credits if enabled
        if self.reposting_settings['add_credits']:
            processed_video = self._add_credits(processed_video, video_data)
        
        # Add watermark if enabled
        if self.reposting_settings['add_watermark']:
            processed_video = self._add_watermark(processed_video, video_data)
        
        return processed_video
    
    def _crop_to_aspect_ratio(self, video: VideoFileClip, target_ratio: float) -> VideoFileClip:
        """
        Crop a video to a target aspect ratio.
        
        Args:
            video (VideoFileClip): Video to crop
            target_ratio (float): Target aspect ratio (width/height)
            
        Returns:
            VideoFileClip: Cropped video
        """
        # Calculate current aspect ratio
        current_width, current_height = video.size
        current_ratio = current_width / current_height
        
        if current_ratio > target_ratio:
            # Video is wider than target, crop width
            new_width = int(current_height * target_ratio)
            x_center = current_width / 2
            x1 = int(x_center - new_width / 2)
            x2 = int(x_center + new_width / 2)
            cropped = video.crop(x1=x1, x2=x2)
        else:
            # Video is taller than target, crop height
            new_height = int(current_width / target_ratio)
            y_center = current_height / 2
            y1 = int(y_center - new_height / 2)
            y2 = int(y_center + new_height / 2)
            cropped = video.crop(y1=y1, y2=y2)
        
        return cropped
    
    def _add_credits(self, video: VideoFileClip, video_data: Dict[str, Any]) -> VideoFileClip:
        """
        Add credits to a video using PIL to create text image.
        
        Args:
            video (VideoFileClip): Video to add credits to
            video_data (Dict[str, Any]): Video data dictionary
            
        Returns:
            VideoFileClip: Video with credits
        """
        try:
            # Import PIL only when needed
            from PIL import Image, ImageDraw, ImageFont
            from moviepy.video.VideoClip import ImageClip
            import os
            import tempfile
            
            # Get video dimensions for positioning
            width, height = video.size
            logger.info(f"Video dimensions: {width}x{height}")
            
            creator = video_data['author']['username']
            credits_text = self.reposting_settings['credits_format'].format(creator=creator)
            logger.info(f"Creating credits text: '{credits_text}'")
            
            # Create a larger image to ensure text is visible
            img_height = 120  # Make taller for better visibility
            img = Image.new('RGBA', (width, img_height), (0, 0, 0, 128))  # Semi-transparent black background
            draw = ImageDraw.Draw(img)
            
            # Try to get a font, with better error handling
            font = None
            try:
                font = ImageFont.truetype("arial.ttf", 30)
                logger.info("Using Arial font for credits")
            except Exception as e:
                logger.warning(f"Arial font not available: {str(e)}")
                try:
                    # Try system fonts
                    system_fonts = ["DejaVuSans.ttf", "FreeSans.ttf", "LiberationSans-Regular.ttf"]
                    for system_font in system_fonts:
                        try:
                            font = ImageFont.truetype(system_font, 30)
                            logger.info(f"Using system font: {system_font}")
                            break
                        except:
                            continue
                except:
                    pass
                
                if font is None:
                    logger.warning("Using default font as fallback")
                    font = ImageFont.load_default()
            
            # Get text dimensions to center it
            text_width = 0
            try:
                # For newer PIL versions
                text_width = draw.textlength(credits_text, font=font)
                logger.info(f"Text width calculated with textlength: {text_width}")
            except AttributeError:
                # Fallback for older PIL versions
                try:
                    text_width, _ = draw.textsize(credits_text, font=font)
                    logger.info(f"Text width calculated with textsize: {text_width}")
                except:
                    # If all fails, estimate width
                    text_width = len(credits_text) * 15  # Rough estimate
                    logger.warning(f"Using estimated text width: {text_width}")
            
            # Center text horizontally and position at bottom of the image
            x = (width - text_width) // 2
            y = (img_height - 40) // 2  # Center text vertically in our image
            logger.info(f"Positioning credits at ({x}, {y}) in text image")
            
            # Draw text with outline for better visibility
            outline_color = (0, 0, 0, 255)  # Black outline
            text_color = (255, 255, 255, 255)  # White text
            
            # Draw black outline
            for offset_x, offset_y in [(-2, -2), (-2, 2), (2, -2), (2, 2)]:
                draw.text((x + offset_x, y + offset_y), credits_text, font=font, fill=outline_color)
            
            # Draw white text on top
            draw.text((x, y), credits_text, font=font, fill=text_color)
            
            # Save the image to a temporary file
            temp_file = tempfile.NamedTemporaryFile(suffix='.png', delete=False)
            temp_filename = temp_file.name
            temp_file.close()
            img.save(temp_filename)
            logger.info(f"Saved credits image to temporary file: {temp_filename}")
            
            try:
                # Create the image clip
                credits_clip = ImageClip(temp_filename)
                logger.info(f"Created image clip with size: {credits_clip.size}")
                
                # Position at the bottom of the video
                clip_pos = (0, height - img_height)
                logger.info(f"Positioning credits clip at {clip_pos}")
                
                # Get the duration from the original video
                clip_duration = None
                if hasattr(video, 'duration') and video.duration is not None:
                    clip_duration = video.duration
                    
                # Method 1: Use set_position
                try:
                    credits_clip = credits_clip.set_position(clip_pos)
                    # Create the composite clip, try different approaches for compatibility
                    try:
                        # First approach - with use_bgclip parameter
                        result = CompositeVideoClip([video, credits_clip], use_bgclip=True)
                        # Explicitly set audio from original video
                        result.audio = video.audio
                        logger.info("Created composite with audio set after creation")
                    except Exception as e_audio:
                        # Second approach - standard composition
                        logger.warning(f"First composite approach failed: {str(e_audio)}")
                        try:
                            result = CompositeVideoClip([video, credits_clip])
                            result.audio = video.audio
                            logger.info("Created composite with standard approach")
                        except Exception as e_standard:
                            logger.warning(f"Standard composite failed: {str(e_standard)}")
                            # Return the original video as fallback
                            result = video
                            logger.info("Using original video due to composite failures")
                    logger.info("Created composite using set_position method")
                except Exception as e1:
                    logger.warning(f"set_position method failed: {str(e1)}")
                    # Method 2: Manual positioning
                    try:
                        # Create the composite clip, try different approaches for compatibility
                        try:
                            # First approach - with use_bgclip parameter
                            result = CompositeVideoClip([video, credits_clip], bg_color=None, use_bgclip=True)
                            # Explicitly set audio from original video
                            result.audio = video.audio
                            logger.info("Created composite with manual positioning")
                        except Exception as e_audio:
                            # Second approach - standard composition
                            logger.warning(f"First manual positioning approach failed: {str(e_audio)}")
                            try:
                                result = CompositeVideoClip([video, credits_clip], bg_color=None)
                                result.audio = video.audio
                                logger.info("Created composite with standard manual positioning")
                            except Exception as e_standard:
                                logger.warning(f"Standard manual positioning failed: {str(e_standard)}")
                                # Return the original video as fallback
                                result = video
                                logger.info("Using original video due to composite failures")
                        logger.info("Created composite using list method")
                    except Exception as e2:
                        logger.error(f"All composite methods failed: {str(e2)}")
                        # Return the original video as fallback
                        result = video
                        logger.info("Returning original video without credits due to composite failures")
                
                # Explicitly set duration on the composite clip
                if clip_duration:
                    try:
                        try:
                            # Method 1: Direct attribute assignment
                            result.duration = clip_duration
                            logger.info(f"Set composite clip duration to {clip_duration:.2f}s via direct assignment")
                        except Exception as d1:
                            # Method 2: Use set_duration method if available
                            logger.warning(f"Direct duration assignment failed: {str(d1)}")
                            if hasattr(result, 'set_duration'):
                                result = result.set_duration(clip_duration)
                                logger.info(f"Set composite clip duration to {clip_duration:.2f}s via set_duration")
                    except Exception as e:
                        logger.warning(f"Failed to set duration on composite clip: {str(e)}")
                
                # Clean up the temporary file
                try:
                    os.unlink(temp_filename)
                    logger.info("Removed temporary image file")
                except Exception as e:
                    logger.warning(f"Failed to remove temp file: {str(e)}")
                
                return result
            except Exception as e:
                logger.error(f"Error creating ImageClip or CompositeVideoClip: {str(e)}")
                # Clean up and return original video
                try:
                    os.unlink(temp_filename)
                except:
                    pass
                return video
        
        except Exception as e:
            logger.error(f"Failed to add credits: {str(e)}")
            return video
    
    def _add_watermark(self, video: VideoFileClip, video_data: Dict[str, Any]) -> VideoFileClip:
        """
        Add watermark using PIL to create text image.
        
        Args:
            video (VideoFileClip): Video to add watermark to
            video_data (Dict[str, Any]): Video data dictionary
            
        Returns:
            VideoFileClip: Video with watermark
        """
        try:
            # Import PIL only when needed
            from PIL import Image, ImageDraw, ImageFont
            from moviepy.video.VideoClip import ImageClip
            import os
            import tempfile
            
            # Get video dimensions for positioning
            width, height = video.size
            logger.info(f"Video dimensions for watermark: {width}x{height}")
            
            watermark_text = "Trending Content"
            logger.info(f"Creating watermark text: '{watermark_text}'")
            
            # Create image with a semi-transparent background
            watermark_width = width // 3  # 1/3 of video width
            watermark_height = 60  # Fixed height
            
            # Create image with semi-transparent black background for better readability
            img = Image.new('RGBA', (watermark_width, watermark_height), (0, 0, 0, 128))
            draw = ImageDraw.Draw(img)
            
            # Try to get a font, with better error handling
            font = None
            try:
                font = ImageFont.truetype("arial.ttf", 24)
                logger.info("Using Arial font for watermark")
            except Exception as e:
                logger.warning(f"Arial font not available for watermark: {str(e)}")
                try:
                    # Try system fonts
                    system_fonts = ["DejaVuSans.ttf", "FreeSans.ttf", "LiberationSans-Regular.ttf"]
                    for system_font in system_fonts:
                        try:
                            font = ImageFont.truetype(system_font, 24)
                            logger.info(f"Using system font for watermark: {system_font}")
                            break
                        except:
                            continue
                except:
                    pass
                
                if font is None:
                    logger.warning("Using default font as fallback for watermark")
                    font = ImageFont.load_default()
            
            # Get text dimensions to center it
            text_width = 0
            try:
                # For newer PIL versions
                text_width = draw.textlength(watermark_text, font=font)
            except AttributeError:
                # Fallback for older PIL versions
                try:
                    text_width, _ = draw.textsize(watermark_text, font=font)
                except:
                    # If all fails, estimate width
                    text_width = len(watermark_text) * 12  # Rough estimate
                    logger.warning(f"Using estimated watermark text width: {text_width}")
            
            # Center text in the watermark image
            x = (watermark_width - text_width) // 2
            y = (watermark_height - 30) // 2  # Center vertically
            logger.info(f"Positioning watermark text at ({x}, {y}) in watermark image")
            
            # Draw text with outline for visibility
            outline_color = (0, 0, 0, 255)  # Black outline
            text_color = (255, 255, 255, 255)  # White text
            
            # Draw outline
            for offset_x, offset_y in [(-1, -1), (-1, 1), (1, -1), (1, 1)]:
                draw.text((x + offset_x, y + offset_y), watermark_text, font=font, fill=outline_color)
                
            # Draw text
            draw.text((x, y), watermark_text, font=font, fill=text_color)
            
            # Save to temporary file
            temp_file = tempfile.NamedTemporaryFile(suffix='.png', delete=False)
            temp_filename = temp_file.name
            temp_file.close()
            img.save(temp_filename)
            logger.info(f"Saved watermark image to temporary file: {temp_filename}")
            
            try:
                # Create the image clip
                watermark_clip = ImageClip(temp_filename)
                logger.info(f"Created watermark clip with size: {watermark_clip.size}")
                
                # Position in top right corner
                clip_pos = (width - watermark_width, 0)
                logger.info(f"Positioning watermark clip at {clip_pos}")
                
                # Get the duration from the original video
                clip_duration = None
                if hasattr(video, 'duration') and video.duration is not None:
                    clip_duration = video.duration
                    
                # Method 1: Use set_position
                try:
                    watermark_clip = watermark_clip.set_position(clip_pos)
                    # Create the composite clip, try different approaches for compatibility
                    try:
                        # First approach - with use_bgclip parameter
                        result = CompositeVideoClip([video, watermark_clip], use_bgclip=True)
                        # Explicitly set audio from original video
                        result.audio = video.audio
                        logger.info("Created composite with audio set after creation")
                    except Exception as e_audio:
                        # Second approach - standard composition
                        logger.warning(f"First composite approach failed: {str(e_audio)}")
                        try:
                            result = CompositeVideoClip([video, watermark_clip])
                            result.audio = video.audio
                            logger.info("Created composite with standard approach")
                        except Exception as e_standard:
                            logger.warning(f"Standard composite failed: {str(e_standard)}")
                            # Return the original video as fallback
                            result = video
                            logger.info("Using original video due to composite failures")
                    logger.info("Created composite using set_position method")
                except Exception as e1:
                    logger.warning(f"set_position method failed for watermark: {str(e1)}")
                    # Method 2: Manual positioning
                    try:
                        # Create the composite clip, try different approaches for compatibility
                        try:
                            # First approach - with use_bgclip parameter
                            result = CompositeVideoClip([video, watermark_clip], bg_color=None, use_bgclip=True)
                            # Explicitly set audio from original video
                            result.audio = video.audio
                            logger.info("Created composite with manual positioning")
                        except Exception as e_audio:
                            # Second approach - standard composition
                            logger.warning(f"First manual positioning approach failed: {str(e_audio)}")
                            try:
                                result = CompositeVideoClip([video, watermark_clip], bg_color=None)
                                result.audio = video.audio
                                logger.info("Created composite with standard manual positioning")
                            except Exception as e_standard:
                                logger.warning(f"Standard manual positioning failed: {str(e_standard)}")
                                # Return the original video as fallback
                                result = video
                                logger.info("Using original video due to composite failures")
                        logger.info("Created composite using list method")
                    except Exception as e2:
                        logger.error(f"All watermark composite methods failed: {str(e2)}")
                        # Return the original video as fallback
                        result = video
                        logger.info("Returning original video without watermark due to composite failures")
                
                # Explicitly set duration on the composite clip
                if clip_duration:
                    try:
                        try:
                            # Method 1: Direct attribute assignment
                            result.duration = clip_duration
                            logger.info(f"Set composite clip duration to {clip_duration:.2f}s via direct assignment")
                        except Exception as d1:
                            # Method 2: Use set_duration method if available
                            logger.warning(f"Direct duration assignment failed: {str(d1)}")
                            if hasattr(result, 'set_duration'):
                                result = result.set_duration(clip_duration)
                                logger.info(f"Set composite clip duration to {clip_duration:.2f}s via set_duration")
                    except Exception as e:
                        logger.warning(f"Failed to set duration on composite clip: {str(e)}")
                
                # Clean up the temporary file
                try:
                    os.unlink(temp_filename)
                    logger.info("Removed temporary image file")
                except Exception as e:
                    logger.warning(f"Failed to remove temp file: {str(e)}")
                
                return result
            except Exception as e:
                logger.error(f"Error creating watermark ImageClip or CompositeVideoClip: {str(e)}")
                # Clean up and return original video
                try:
                    os.unlink(temp_filename)
                except:
                    pass
                return video
        
        except Exception as e:
            logger.error(f"Failed to add watermark: {str(e)}")
            return video
    
    def process_batch(self, video_files: List[str], video_data_list: List[Dict[str, Any]]) -> List[str]:
        """
        Process a batch of videos.
        
        Args:
            video_files (List[str]): List of paths to video files
            video_data_list (List[Dict[str, Any]]): List of video data dictionaries
            
        Returns:
            List[str]: List of paths to processed video files
        """
        processed_files = []
        
        for video_file, video_data in zip(video_files, video_data_list):
            processed_file = self.process_video(video_file, video_data)
            if processed_file:
                processed_files.append(processed_file)
        
        return processed_files 