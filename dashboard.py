#!/usr/bin/env python3
"""
Dashboard for TikTok to YouTube Bridge
Provides real-time monitoring and control of the bridge application.
"""
import os
import json
import logging
import sqlite3
import threading
import time
import psutil
import sys
from datetime import datetime, timedelta
from flask import Flask, render_template, jsonify, request, redirect, url_for
from werkzeug.serving import run_simple
import config
from youtube_uploader import YouTubeUploader
from video_history import VideoHistory
import math
from content_analyzer import ContentAnalyzer
from pathlib import Path

# Configure logging
logging.basicConfig(
    level=getattr(logging, config.LOGGING['level']),
    format=config.LOGGING['log_format'],
    handlers=[
        logging.FileHandler(config.LOGGING['log_file']),
        logging.StreamHandler(sys.stdout)  # Add console output
    ]
)
logger = logging.getLogger("dashboard")

# Initialize Flask app
app = Flask(__name__, 
            template_folder=os.path.join(os.path.dirname(__file__), 'dashboard/templates'),
            static_folder=os.path.join(os.path.dirname(__file__), 'dashboard/static'))

# Database setup
DB_PATH = os.path.join(os.path.dirname(__file__), 'dashboard.db')

# Global variable to track if bridge process is running
bridge_process_status = {
    "status": "stopped",
    "next_run": None
}

def init_db():
    """Initialize the SQLite database for dashboard metrics."""
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        
        # Create tables if they don't exist
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS processing_stats (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            videos_processed INTEGER,
            videos_uploaded INTEGER,
            videos_failed INTEGER,
            channels_processed INTEGER
        )
        ''')
        
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS uploads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            channel TEXT,
            video_id TEXT,
            video_title TEXT,
            youtube_id TEXT,
            status TEXT
        )
        ''')
        
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS system_status (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            status TEXT,
            cpu_usage REAL,
            memory_usage REAL,
            disk_usage REAL,
            next_run TEXT
        )
        ''')
        
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS token_status (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            is_valid INTEGER,
            expiry TEXT,
            has_refresh_token INTEGER,
            message TEXT
        )
        ''')
        
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS config_settings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            setting_key TEXT,
            setting_value TEXT,
            category TEXT
        )
        ''')
        
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS youtube_metrics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            youtube_id TEXT,
            views INTEGER,
            likes INTEGER,
            comments INTEGER,
            favorites INTEGER,
            tiktok_views INTEGER,
            tiktok_likes INTEGER,
            tiktok_comments INTEGER,
            tiktok_shares INTEGER
        )
        ''')
        
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS metrics_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            youtube_id TEXT,
            platform TEXT,
            views INTEGER,
            likes INTEGER,
            comments INTEGER,
            shares INTEGER
        )
        ''')
        
        # New tables for the enhanced features
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS youtube_api_quota (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            date TEXT,
            used INTEGER,
            remaining INTEGER,
            operation TEXT,
            operation_count INTEGER,
            operation_cost INTEGER
        )
        ''')
        
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS dynamic_thresholds (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            channel TEXT,
            channel_size TEXT,
            avg_views INTEGER,
            median_views INTEGER,
            percentile_75 INTEGER,
            threshold INTEGER
        )
        ''')
        
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS file_cleanup (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            directory TEXT,
            files_removed INTEGER,
            space_freed_mb REAL,
            retention_days INTEGER
        )
        ''')
        
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS channel_groups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            group_name TEXT,
            channels TEXT,
            publish_days TEXT,
            last_run TEXT,
            next_run TEXT
        )
        ''')
        
        conn.commit()
        logger.info("Database initialized")

def update_token_status():
    """Update token status in the database."""
    uploader = YouTubeUploader()
    is_valid, message = uploader.check_token_validity()
    
    if is_valid and uploader.credentials and uploader.credentials.expiry:
        expiry = uploader.credentials.expiry.strftime('%Y-%m-%d %H:%M:%S')
        has_refresh_token = 1 if uploader.credentials.refresh_token else 0
    else:
        expiry = None
        has_refresh_token = 0
    
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute('''
        INSERT INTO token_status (timestamp, is_valid, expiry, has_refresh_token, message)
        VALUES (?, ?, ?, ?, ?)
        ''', (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), 1 if is_valid else 0, 
              expiry, has_refresh_token, message))
        conn.commit()
    
    logger.info(f"Token status updated: {is_valid}, {message}")
    return is_valid, message, expiry, has_refresh_token

def update_system_status():
    """Update system status in the database with real system metrics."""
    cpu_usage = psutil.cpu_percent()
    memory_usage = psutil.virtual_memory().percent
    
    # Get disk usage for the drive where the application is running
    disk_usage = psutil.disk_usage(os.path.abspath(os.sep)).percent
    
    # Use global bridge status
    status = bridge_process_status["status"]
    next_run = bridge_process_status["next_run"]
    
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute('''
        INSERT INTO system_status (timestamp, status, cpu_usage, memory_usage, disk_usage, next_run)
        VALUES (?, ?, ?, ?, ?, ?)
        ''', (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), status, cpu_usage, memory_usage, disk_usage, next_run))
        conn.commit()
    
    logger.info(f"System status updated: CPU {cpu_usage}%, Memory {memory_usage}%, Disk {disk_usage}%")
    return status, cpu_usage, memory_usage, disk_usage, next_run

def get_channels_from_file():
    """Read the channels.json file and return the channels configuration."""
    channels_file = os.path.join(os.path.dirname(__file__), 'channels.json')
    if os.path.exists(channels_file):
        try:
            with open(channels_file, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error reading channels.json: {str(e)}")
    return []

def save_channels_to_file(channels_data):
    """Save the channels configuration to the channels.json file."""
    channels_file = os.path.join(os.path.dirname(__file__), 'channels.json')
    try:
        with open(channels_file, 'w') as f:
            json.dump(channels_data, f, indent=4)
        logger.info("Channels configuration saved")
        return True
    except Exception as e:
        logger.error(f"Error saving channels.json: {str(e)}")
        return False

def get_config_settings():
    """Get configuration settings from config.py as a dictionary."""
    settings = {
        "content_filters": config.CONTENT_FILTERS,
        "reposting_settings": config.REPOSTING_SETTINGS,
        "youtube_defaults": config.YOUTUBE_DEFAULTS,
        "tiktok_scraping": config.TIKTOK_SCRAPING
    }
    return settings

def save_config_to_db(settings_dict, category):
    """Save configuration settings to the database."""
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        for key, value in settings_dict.items():
            if isinstance(value, dict):
                # Recursively save nested dictionaries
                save_config_to_db(value, f"{category}.{key}")
            else:
                # Convert value to string for storage
                value_str = str(value)
                
                # Check if this setting already exists
                cursor.execute('''
                SELECT id FROM config_settings 
                WHERE setting_key = ? AND category = ?
                ''', (key, category))
                
                existing = cursor.fetchone()
                
                if existing:
                    # Update existing setting
                    cursor.execute('''
                    UPDATE config_settings 
                    SET timestamp = ?, setting_value = ? 
                    WHERE setting_key = ? AND category = ?
                    ''', (timestamp, value_str, key, category))
                else:
                    # Insert new setting
                    cursor.execute('''
                    INSERT INTO config_settings (timestamp, setting_key, setting_value, category)
                    VALUES (?, ?, ?, ?)
                    ''', (timestamp, key, value_str, category))
        
        conn.commit()
    logger.info(f"Saved {category} settings to database")

def apply_config_changes(category, settings):
    """Apply configuration changes to the runtime config and save to relevant files."""
    try:
        # This would need to be implemented based on the specific config structure
        # For now, just log that we would apply changes
        logger.info(f"Applying {category} configuration changes: {settings}")
        return True
    except Exception as e:
        logger.error(f"Error applying config changes: {str(e)}")
        return False

def update_youtube_metrics():
    """Update YouTube metrics for all uploaded videos."""
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            # Get all successful uploads with YouTube IDs
            cursor.execute('''
            SELECT DISTINCT youtube_id 
            FROM uploads 
            WHERE status = 'success' AND youtube_id IS NOT NULL
            ''')
            
            rows = cursor.fetchall()
            youtube_ids = [row['youtube_id'] for row in rows]
            
            if not youtube_ids:
                logger.info("No YouTube videos found to update metrics")
                return False
                
            # Get metrics for these videos
            uploader = YouTubeUploader()
            metrics = uploader.get_youtube_metrics(youtube_ids)
            
            # Get original TikTok metrics from video history
            history = VideoHistory()
            
            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            
            # For each video, update the metrics
            for youtube_id, yt_metrics in metrics.items():
                # Get the TikTok video ID for this YouTube video
                cursor.execute('''
                SELECT video_id, channel FROM uploads WHERE youtube_id = ?
                ''', (youtube_id,))
                
                upload_row = cursor.fetchone()
                if not upload_row:
                    continue
                    
                tiktok_video_id = upload_row['video_id']
                tiktok_channel = upload_row['channel']
                
                # Get TikTok metrics from history
                channel_history = history.get_channel_history(tiktok_channel)
                
                tiktok_metrics = {
                    "views": 0,
                    "likes": 0,
                    "comments": 0,
                    "shares": 0
                }
                
                # Find this video in the history
                for video in channel_history:
                    if video.get('video_id') == tiktok_video_id:
                        tiktok_metrics = video.get('metrics', tiktok_metrics)
                        break
                
                # Store metrics in the database
                cursor.execute('''
                SELECT id FROM youtube_metrics WHERE youtube_id = ?
                ''', (youtube_id,))
                
                existing = cursor.fetchone()
                
                if existing:
                    # Update existing record
                    cursor.execute('''
                    UPDATE youtube_metrics 
                    SET timestamp = ?, views = ?, likes = ?, comments = ?, favorites = ?,
                        tiktok_views = ?, tiktok_likes = ?, tiktok_comments = ?, tiktok_shares = ?
                    WHERE id = ?
                    ''', (
                        timestamp, 
                        yt_metrics.get('views', 0), 
                        yt_metrics.get('likes', 0), 
                        yt_metrics.get('comments', 0),
                        yt_metrics.get('favorites', 0),
                        tiktok_metrics.get('views', 0),
                        tiktok_metrics.get('likes', 0),
                        tiktok_metrics.get('comments', 0),
                        tiktok_metrics.get('shares', 0),
                        existing['id']
                    ))
                else:
                    # Insert new record
                    cursor.execute('''
                    INSERT INTO youtube_metrics (
                        timestamp, youtube_id, views, likes, comments, favorites,
                        tiktok_views, tiktok_likes, tiktok_comments, tiktok_shares
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (
                        timestamp,
                        youtube_id,
                        yt_metrics.get('views', 0),
                        yt_metrics.get('likes', 0),
                        yt_metrics.get('comments', 0),
                        yt_metrics.get('favorites', 0),
                        tiktok_metrics.get('views', 0),
                        tiktok_metrics.get('likes', 0),
                        tiktok_metrics.get('comments', 0),
                        tiktok_metrics.get('shares', 0)
                    ))
                
                # Add entry to metrics history
                cursor.execute('''
                INSERT INTO metrics_history (
                    timestamp, youtube_id, platform, views, likes, comments, shares
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ''', (
                    timestamp,
                    youtube_id,
                    'youtube',
                    yt_metrics.get('views', 0),
                    yt_metrics.get('likes', 0),
                    yt_metrics.get('comments', 0),
                    0  # YouTube doesn't provide shares
                ))
                
                # Add entry for TikTok metrics history
                cursor.execute('''
                INSERT INTO metrics_history (
                    timestamp, youtube_id, platform, views, likes, comments, shares
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ''', (
                    timestamp,
                    youtube_id,
                    'tiktok',
                    tiktok_metrics.get('views', 0),
                    tiktok_metrics.get('likes', 0),
                    tiktok_metrics.get('comments', 0),
                    tiktok_metrics.get('shares', 0)
                ))
            
            conn.commit()
            logger.info(f"Updated YouTube metrics for {len(metrics)} videos")
            return True
            
    except Exception as e:
        logger.error(f"Error updating YouTube metrics: {str(e)}")
        return False

def background_monitor():
    """Background thread to continuously monitor system and token status."""
    while True:
        try:
            # Update system stats
            update_system_status()
            
            # Update token status (less frequently)
            if int(time.time()) % 3600 < 60:  # Once every hour
                update_token_status()
                
            # Update YouTube metrics (less frequently)
            if int(time.time()) % 3600 < 120:  # Once every hour
                update_youtube_metrics()
                
        except Exception as e:
            logger.error(f"Error in background monitor: {str(e)}")
        
        # Sleep for a while before next update
        time.sleep(30)

# Routes
@app.route('/')
def index():
    """Dashboard home page."""
    # Get latest system status
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Get latest system status
        cursor.execute('SELECT * FROM system_status ORDER BY id DESC LIMIT 1')
        system_status = cursor.fetchone()
        
        # Get latest token status
        cursor.execute('SELECT * FROM token_status ORDER BY id DESC LIMIT 1')
        token_status = cursor.fetchone()
        
        # Get recent processing stats (last 7 days)
        cursor.execute('SELECT * FROM processing_stats ORDER BY timestamp DESC LIMIT 7')
        processing_stats = cursor.fetchall()
        
        # Get recent uploads
        cursor.execute('SELECT * FROM uploads ORDER BY timestamp DESC LIMIT 10')
        recent_uploads = cursor.fetchall()
        
        # Get total stats
        cursor.execute('''
        SELECT SUM(videos_processed) as total_processed, 
               SUM(videos_uploaded) as total_uploaded,
               SUM(videos_failed) as total_failed
        FROM processing_stats
        ''')
        totals = cursor.fetchone()
    
    # Check for real token status
    try:
        real_token_valid, real_token_message, real_token_expiry, real_token_has_refresh = update_token_status()
    except Exception as e:
        logger.error(f"Error checking token status: {str(e)}")
        real_token_valid = False
        real_token_message = f"Error checking token: {str(e)}"
        real_token_expiry = None
        real_token_has_refresh = False
    
    # Also update system status
    try:
        status, cpu, memory, disk, next_run = update_system_status()
    except Exception as e:
        logger.error(f"Error updating system status: {str(e)}")
    
    # Get YouTube API quota data
    quota_data = get_youtube_api_quota()
    
    # Get dynamic thresholds data
    thresholds_data = get_dynamic_thresholds()
    
    # Get file cleanup statistics
    cleanup_data = get_cleanup_stats()
    
    # Get channel groups data
    groups_data = get_channel_groups()
    
    return render_template(
        'index.html',
        system_status=system_status,
        token_status=token_status,
        processing_stats=processing_stats,
        recent_uploads=recent_uploads,
        totals=totals,
        real_token={
            "valid": real_token_valid,
            "message": real_token_message,
            "expiry": real_token_expiry,
            "has_refresh": real_token_has_refresh
        },
        timestamp=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        quota_data=quota_data,
        thresholds_data=thresholds_data,
        cleanup_data=cleanup_data,
        groups_data=groups_data
    )

@app.route('/api/stats')
def api_stats():
    """API endpoint for dashboard stats."""
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Get processing stats for the past week
        cursor.execute('SELECT * FROM processing_stats ORDER BY timestamp DESC LIMIT 7')
        processing_stats = [dict(row) for row in cursor.fetchall()]
        
        # Get latest system status
        cursor.execute('SELECT * FROM system_status ORDER BY id DESC LIMIT 1')
        system_status = dict(cursor.fetchone() or {"status": "unknown"})
        
        # Get latest token status
        cursor.execute('SELECT * FROM token_status ORDER BY id DESC LIMIT 1')
        token_row = cursor.fetchone()
        token_status = dict(token_row) if token_row else {"is_valid": 0, "message": "No token data"}
    
    return jsonify({
        "system_status": system_status,
        "token_status": token_status,
        "processing_stats": processing_stats
    })

@app.route('/api/uploads')
def api_uploads():
    """API endpoint for recent uploads."""
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Get recent uploads
        cursor.execute('SELECT * FROM uploads ORDER BY timestamp DESC LIMIT 20')
        uploads = [dict(row) for row in cursor.fetchall()]
    
    return jsonify({"uploads": uploads})

@app.route('/authenticate')
def authenticate():
    """Force YouTube re-authentication."""
    try:
        uploader = YouTubeUploader()
        result = uploader.authenticate()
        if result:
            update_token_status()
            return jsonify({"success": True, "message": "Authentication successful"})
        else:
            return jsonify({"success": False, "message": "Authentication failed"})
    except Exception as e:
        logger.error(f"Authentication error: {str(e)}")
        return jsonify({"success": False, "message": f"Error: {str(e)}"})

@app.route('/controls', methods=['POST'])
def controls():
    """Route for controlling the bridge process."""
    action = request.form.get('action')
    
    if not action:
        return jsonify({'status': 'error', 'message': 'No action specified'})
    
    if action == 'restart':
        # Run the restart script if it exists
        try:
            # Execute restart command
            os.system('nohup python3 main.py &')
            return jsonify({'status': 'success', 'message': 'Bridge restarted successfully'})
        except Exception as e:
            logger.error(f"Error restarting bridge: {str(e)}")
            return jsonify({'status': 'error', 'message': f'Error restarting bridge: {str(e)}'})
    
    elif action == 'pause':
        # Update status
        update_system_status()
        
        # You would implement a mechanism to pause the process here
        return jsonify({'status': 'success', 'message': 'Bridge paused (not implemented)'})
    
    elif action == 'resume':
        # Update status
        update_system_status()
        
        # You would implement a mechanism to resume the process here
        return jsonify({'status': 'success', 'message': 'Bridge resumed (not implemented)'})
    
    elif action == 'run_group':
        group = request.form.get('group')
        if not group:
            return jsonify({'status': 'error', 'message': 'No group specified'})
        
        try:
            # Check for new format file first
            new_format_file = f'channels-{group}.json'
            legacy_format_file = f'channels{group}.json'
            
            if os.path.exists(new_format_file):
                config_file = new_format_file
            elif os.path.exists(legacy_format_file):
                config_file = legacy_format_file
            else:
                return jsonify({'status': 'error', 'message': f'Group configuration file not found for {group}'})
            
            # Run the main script with the group parameter
            command = f'nohup python3 main.py --group {group} &'
            os.system(command)
            
            logger.info(f"Started processing group {group} with command: {command}")
            
            return jsonify({
                'status': 'success', 
                'message': f'Started processing for group {group}. Check logs for details.'
            })
        except Exception as e:
            logger.error(f"Error running group {group}: {str(e)}")
            return jsonify({'status': 'error', 'message': f'Error running group {group}: {str(e)}'})
            
    else:
        return jsonify({'status': 'error', 'message': f'Unknown action: {action}'})

@app.route('/channels', methods=['GET', 'POST'])
def channels():
    """Handle channel configuration."""
    if request.method == 'POST':
        try:
            channels_data = request.json
            success = save_channels_to_file(channels_data)
            return jsonify({"success": success})
        except Exception as e:
            logger.error(f"Error saving channels: {str(e)}")
            return jsonify({"success": False, "error": str(e)})
    else:
        # GET request
        channels = get_channels_from_file()
        return jsonify({"channels": channels})

@app.route('/config', methods=['GET', 'POST'])
def config_settings():
    """Handle configuration settings."""
    if request.method == 'POST':
        try:
            category = request.json.get('category')
            settings = request.json.get('settings')
            
            # Save to database
            save_config_to_db(settings, category)
            
            # Apply changes to runtime
            success = apply_config_changes(category, settings)
            
            return jsonify({"success": success})
        except Exception as e:
            logger.error(f"Error saving config: {str(e)}")
            return jsonify({"success": False, "error": str(e)})
    else:
        # GET request
        settings = get_config_settings()
        return jsonify(settings)

def record_upload(channel, video_id, video_title, youtube_id, status):
    """Record a video upload in the database."""
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute('''
        INSERT INTO uploads (timestamp, channel, video_id, video_title, youtube_id, status)
        VALUES (?, ?, ?, ?, ?, ?)
        ''', (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), channel, video_id, 
              video_title, youtube_id, status))
        conn.commit()
    logger.info(f"Recorded upload: {video_title} - {status}")

def update_processing_stats(videos_processed, videos_uploaded, videos_failed, channels_processed):
    """Update processing statistics in the database."""
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        
        # Check if we already have a record for today
        today = datetime.now().strftime('%Y-%m-%d')
        cursor.execute('''
        SELECT id, videos_processed, videos_uploaded, videos_failed, channels_processed 
        FROM processing_stats 
        WHERE timestamp LIKE ?
        ''', (f"{today}%",))
        
        existing = cursor.fetchone()
        
        if existing:
            # Update existing record
            cursor.execute('''
            UPDATE processing_stats 
            SET videos_processed = videos_processed + ?,
                videos_uploaded = videos_uploaded + ?,
                videos_failed = videos_failed + ?,
                channels_processed = channels_processed + ?
            WHERE id = ?
            ''', (videos_processed, videos_uploaded, videos_failed, channels_processed, existing[0]))
        else:
            # Insert new record
            cursor.execute('''
            INSERT INTO processing_stats (timestamp, videos_processed, videos_uploaded, videos_failed, channels_processed)
            VALUES (?, ?, ?, ?, ?)
            ''', (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), 
                  videos_processed, videos_uploaded, videos_failed, channels_processed))
        
        conn.commit()
    logger.info(f"Updated processing stats: {videos_processed} processed, {videos_uploaded} uploaded, {videos_failed} failed")

def run_dashboard(host='0.0.0.0', port=8080, debug=False):
    """Run the dashboard web server."""
    logger.info(f"Starting dashboard on http://{host}:{port}")
    
    # Initialize database
    init_db()
    
    # Update token status on startup
    update_token_status()
    
    # Start background monitoring thread
    monitor_thread = threading.Thread(target=background_monitor)
    monitor_thread.daemon = True
    monitor_thread.start()
    
    # Run Flask app
    run_simple(host, port, app, use_reloader=debug, use_debugger=debug)

def start_dashboard_thread():
    """Start the dashboard in a separate thread."""
    dashboard_thread = threading.Thread(target=lambda: run_dashboard(host='0.0.0.0', port=8080))
    dashboard_thread.daemon = True
    dashboard_thread.start()
    logger.info("Dashboard started in background thread")
    return dashboard_thread

@app.route('/api/logs')
def api_logs():
    """API endpoint for application logs."""
    level = request.args.get('level', 'ALL')
    lines = int(request.args.get('lines', '100'))
    
    log_file = config.LOGGING['log_file']
    
    if not os.path.exists(log_file):
        return jsonify({"logs": []})
    
    try:
        # Read the log file
        with open(log_file, 'r', encoding='utf-8', errors='replace') as f:
            log_lines = f.readlines()
        
        # Limit to the requested number of lines (from the end)
        log_lines = log_lines[-lines:]
        
        # Filter by level if specified
        if level != 'ALL':
            log_lines = [line for line in log_lines if level in line]
        
        return jsonify({"logs": log_lines})
    except Exception as e:
        logger.error(f"Error reading log file: {str(e)}")
        return jsonify({"logs": [], "error": str(e)})

@app.route('/api/video/<youtube_id>')
def api_video(youtube_id):
    """API endpoint for embedding a YouTube video."""
    if not youtube_id:
        return jsonify({"error": "No YouTube ID provided"})
    
    embed_html = f'''
    <iframe 
        width="100%" 
        height="315" 
        src="https://www.youtube.com/embed/{youtube_id}" 
        frameborder="0" 
        allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture" 
        allowfullscreen>
    </iframe>
    '''
    
    return jsonify({"embed_html": embed_html})

@app.route('/api/analytics')
def api_analytics():
    """API endpoint for analytics data."""
    days = int(request.args.get('days', '30'))
    
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Set the date range
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days)
        start_date_str = start_date.strftime('%Y-%m-%d')
        
        # Get daily stats for the activity chart
        cursor.execute('''
        SELECT 
            strftime('%Y-%m-%d', timestamp) as date,
            SUM(videos_processed) as processed,
            SUM(videos_uploaded) as uploaded,
            SUM(videos_failed) as failed
        FROM processing_stats
        WHERE timestamp >= ?
        GROUP BY date
        ORDER BY date
        ''', (start_date_str,))
        
        daily_stats = [dict(row) for row in cursor.fetchall()]
        
        # Get channel stats
        cursor.execute('''
        SELECT 
            channel,
            COUNT(*) as total,
            SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) as successful,
            MAX(timestamp) as last_upload
        FROM uploads
        WHERE timestamp >= ?
        GROUP BY channel
        ORDER BY total DESC
        ''', (start_date_str,))
        
        channel_stats = [dict(row) for row in cursor.fetchall()]
        
        # Calculate success rate
        total_uploads = sum(stat['total'] for stat in channel_stats) if channel_stats else 0
        successful_uploads = sum(stat['successful'] for stat in channel_stats) if channel_stats else 0
        success_rate = round((successful_uploads / total_uploads) * 100 if total_uploads > 0 else 0, 1)
        
        # Calculate average uploads per day
        num_days = min(days, len(daily_stats)) if daily_stats else 1
        avg_uploads_per_day = round(total_uploads / num_days, 1)
        
        # Get top channel
        top_channel = channel_stats[0]['channel'] if channel_stats else "None"
    
    return jsonify({
        "daily_stats": daily_stats,
        "channel_stats": channel_stats,
        "summary": {
            "total_uploads": total_uploads,
            "successful_uploads": successful_uploads,
            "success_rate": success_rate,
            "avg_uploads_per_day": avg_uploads_per_day,
            "top_channel": top_channel,
            "period_days": days
        }
    })

@app.route('/api/metrics')
def api_metrics():
    """API endpoint for video metrics comparison."""
    days = int(request.args.get('days', '30'))
    limit = int(request.args.get('limit', '10'))
    
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Set the date range
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days)
        start_date_str = start_date.strftime('%Y-%m-%d')
        
        # Get videos with both TikTok and YouTube metrics
        cursor.execute('''
        SELECT 
            u.video_title,
            u.channel,
            u.youtube_id,
            ym.views as youtube_views,
            ym.likes as youtube_likes,
            ym.comments as youtube_comments,
            ym.tiktok_views,
            ym.tiktok_likes,
            ym.tiktok_comments,
            ym.tiktok_shares,
            u.timestamp as upload_date
        FROM uploads u
        JOIN youtube_metrics ym ON u.youtube_id = ym.youtube_id
        WHERE u.timestamp >= ? AND u.status = 'success'
        ORDER BY u.timestamp DESC
        LIMIT ?
        ''', (start_date_str, limit))
        
        metrics = [dict(row) for row in cursor.fetchall()]
        
        # Calculate engagement stats
        for video in metrics:
            # Calculate YouTube engagement rate
            yt_views = video['youtube_views']
            yt_engagement = (video['youtube_likes'] + video['youtube_comments']) / max(yt_views, 1) * 100
            video['youtube_engagement'] = round(yt_engagement, 2)
            
            # Calculate TikTok engagement rate
            tk_views = video['tiktok_views']
            tk_engagement = (video['tiktok_likes'] + video['tiktok_comments'] + video['tiktok_shares']) / max(tk_views, 1) * 100
            video['tiktok_engagement'] = round(tk_engagement, 2)
            
            # Calculate ratios (YouTube compared to TikTok)
            video['views_ratio'] = round(yt_views / max(tk_views, 1) * 100, 2) if tk_views > 0 else 0
            video['likes_ratio'] = round(video['youtube_likes'] / max(video['tiktok_likes'], 1) * 100, 2) if video['tiktok_likes'] > 0 else 0
            video['comments_ratio'] = round(video['youtube_comments'] / max(video['tiktok_comments'], 1) * 100, 2) if video['tiktok_comments'] > 0 else 0
        
        # Calculate aggregate stats
        total_yt_views = sum(video['youtube_views'] for video in metrics)
        total_tk_views = sum(video['tiktok_views'] for video in metrics)
        total_yt_likes = sum(video['youtube_likes'] for video in metrics)
        total_tk_likes = sum(video['tiktok_likes'] for video in metrics)
        total_yt_comments = sum(video['youtube_comments'] for video in metrics)
        total_tk_comments = sum(video['tiktok_comments'] for video in metrics)
        
        avg_views_ratio = round(total_yt_views / max(total_tk_views, 1) * 100, 2) if total_tk_views > 0 else 0
        avg_likes_ratio = round(total_yt_likes / max(total_tk_likes, 1) * 100, 2) if total_tk_likes > 0 else 0
        avg_comments_ratio = round(total_yt_comments / max(total_tk_comments, 1) * 100, 2) if total_tk_comments > 0 else 0
        
        # Average engagement rates
        avg_yt_engagement = sum(video['youtube_engagement'] for video in metrics) / max(len(metrics), 1)
        avg_tk_engagement = sum(video['tiktok_engagement'] for video in metrics) / max(len(metrics), 1)
        
        # Get metrics by channel
        cursor.execute('''
        SELECT 
            u.channel,
            SUM(ym.views) as youtube_views,
            SUM(ym.likes) as youtube_likes,
            SUM(ym.comments) as youtube_comments,
            SUM(ym.tiktok_views) as tiktok_views,
            SUM(ym.tiktok_likes) as tiktok_likes,
            SUM(ym.tiktok_comments) as tiktok_comments,
            COUNT(u.id) as video_count
        FROM uploads u
        JOIN youtube_metrics ym ON u.youtube_id = ym.youtube_id
        WHERE u.timestamp >= ? AND u.status = 'success'
        GROUP BY u.channel
        ORDER BY video_count DESC
        ''', (start_date_str,))
        
        channel_metrics = [dict(row) for row in cursor.fetchall()]
        
        # Calculate channel engagement rates
        for channel in channel_metrics:
            yt_views = channel['youtube_views']
            yt_engagement = (channel['youtube_likes'] + channel['youtube_comments']) / max(yt_views, 1) * 100
            channel['youtube_engagement'] = round(yt_engagement, 2)
            
            tk_views = channel['tiktok_views']
            tk_engagement = (channel['tiktok_likes'] + channel['tiktok_comments']) / max(tk_views, 1) * 100
            channel['tiktok_engagement'] = round(tk_engagement, 2)
            
            # Calculate view ratio
            channel['views_ratio'] = round(yt_views / max(tk_views, 1) * 100, 2) if tk_views > 0 else 0
    
    return jsonify({
        "videos": metrics,
        "channels": channel_metrics,
        "summary": {
            "total_videos": len(metrics),
            "youtube_views": total_yt_views,
            "tiktok_views": total_tk_views,
            "youtube_likes": total_yt_likes,
            "tiktok_likes": total_tk_likes,
            "youtube_comments": total_yt_comments,
            "tiktok_comments": total_tk_comments,
            "avg_views_ratio": avg_views_ratio,
            "avg_likes_ratio": avg_likes_ratio,
            "avg_comments_ratio": avg_comments_ratio,
            "avg_youtube_engagement": round(avg_yt_engagement, 2),
            "avg_tiktok_engagement": round(avg_tk_engagement, 2)
        }
    })

@app.route('/api/metrics/growth/<youtube_id>')
def api_metrics_growth(youtube_id):
    """API endpoint for tracking metrics growth over time for a specific video."""
    days = int(request.args.get('days', '30'))
    
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Set the date range
        end_date = datetime.now()
        start_date = end_date - timedelta(days=days)
        start_date_str = start_date.strftime('%Y-%m-%d')
        
        # Get metrics history for this video
        cursor.execute('''
        SELECT 
            strftime('%Y-%m-%d', timestamp) as date,
            platform,
            AVG(views) as views,
            AVG(likes) as likes,
            AVG(comments) as comments,
            AVG(shares) as shares
        FROM metrics_history
        WHERE youtube_id = ? AND timestamp >= ?
        GROUP BY date, platform
        ORDER BY date
        ''', (youtube_id, start_date_str))
        
        rows = cursor.fetchall()
        
        # Format data by platform and date
        dates = []
        youtube_data = {'views': [], 'likes': [], 'comments': []}
        tiktok_data = {'views': [], 'likes': [], 'comments': [], 'shares': []}
        
        current_date = None
        
        for row in rows:
            date = row['date']
            
            # Add date to the dates list if it's new
            if date != current_date:
                dates.append(date)
                current_date = date
            
            # Add metrics to the appropriate platform
            if row['platform'] == 'youtube':
                youtube_data['views'].append(row['views'])
                youtube_data['likes'].append(row['likes'])
                youtube_data['comments'].append(row['comments'])
            else:  # tiktok
                tiktok_data['views'].append(row['views'])
                tiktok_data['likes'].append(row['likes'])
                tiktok_data['comments'].append(row['comments'])
                tiktok_data['shares'].append(row['shares'])
        
        # Get video title
        cursor.execute('SELECT video_title FROM uploads WHERE youtube_id = ?', (youtube_id,))
        title_row = cursor.fetchone()
        video_title = title_row['video_title'] if title_row else 'Unknown Video'
    
    return jsonify({
        'video_id': youtube_id,
        'video_title': video_title,
        'dates': dates,
        'youtube': youtube_data,
        'tiktok': tiktok_data
    })

# New function to track deleted YouTube videos
def track_deleted_youtube_video(youtube_id):
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute('''
        UPDATE uploads SET status = 'deleted' WHERE youtube_id = ?
        ''', (youtube_id,))
        conn.commit()
    logger.info(f"Video with YouTube ID {youtube_id} marked as deleted in dashboard.")

@app.route('/api/video/<youtube_id>/delete', methods=['POST'])
def delete_video(youtube_id):
    track_deleted_youtube_video(youtube_id)
    return jsonify({"status": "success", "message": f"Video {youtube_id} marked as deleted."})

@app.route('/api/deleted-videos')
def get_deleted_videos():
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute('SELECT * FROM uploads WHERE status = "deleted" ORDER BY timestamp DESC')
        deleted_videos = [dict(row) for row in cursor.fetchall()]
    return jsonify({"deleted_videos": deleted_videos})

@app.route('/api/cleanup', methods=['POST'])
def cleanup_old_data():
    days = int(request.json.get('days', 30))
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute('DELETE FROM processing_stats WHERE timestamp < datetime("now", ?)', (f'-{days} days',))
        cursor.execute('DELETE FROM metrics_history WHERE timestamp < datetime("now", ?)', (f'-{days} days',))
        conn.commit()
    return jsonify({"status": "success", "message": f"Cleaned up data older than {days} days."})

@app.route('/api/dashboard-summary')
def dashboard_summary():
    """API endpoint for a comprehensive dashboard summary."""
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # Get latest system status
        cursor.execute('SELECT * FROM system_status ORDER BY id DESC LIMIT 1')
        system_status = dict(cursor.fetchone() or {"status": "unknown"})
        
        # Get latest token status
        cursor.execute('SELECT * FROM token_status ORDER BY id DESC LIMIT 1')
        token_row = cursor.fetchone()
        token_status = dict(token_row) if token_row else {"is_valid": 0, "message": "No token data"}
        
        # Get recent processing stats
        cursor.execute('SELECT * FROM processing_stats ORDER BY timestamp DESC LIMIT 7')
        processing_stats = [dict(row) for row in cursor.fetchall()]
        
        # Get total stats
        cursor.execute('''
        SELECT SUM(videos_processed) as total_processed, 
               SUM(videos_uploaded) as total_uploaded,
               SUM(videos_failed) as total_failed
        FROM processing_stats
        ''')
        totals = dict(cursor.fetchone() or {})
        
        # Get recent uploads
        cursor.execute('SELECT * FROM uploads ORDER BY timestamp DESC LIMIT 10')
        recent_uploads = [dict(row) for row in cursor.fetchall()]
        
        # Get deleted videos
        cursor.execute('SELECT * FROM uploads WHERE status = "deleted" ORDER BY timestamp DESC LIMIT 10')
        deleted_videos = [dict(row) for row in cursor.fetchall()]
        
        # Get channel stats
        cursor.execute('''
        SELECT channel, COUNT(*) as total
        FROM uploads
        GROUP BY channel
        ORDER BY total DESC
        ''')
        channel_stats = [dict(row) for row in cursor.fetchall()]
    
    return jsonify({
        "system_status": system_status,
        "token_status": token_status,
        "processing_stats": processing_stats,
        "totals": totals,
        "recent_uploads": recent_uploads,
        "deleted_videos": deleted_videos,
        "channel_stats": channel_stats,
        "timestamp": datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    })

# Add new function to get YouTube API quota data
def get_youtube_api_quota():
    """Get YouTube API quota data from the log file."""
    quota_file = os.path.join(os.path.dirname(__file__), 'youtube_api_quota.json')
    if os.path.exists(quota_file):
        try:
            with open(quota_file, 'r') as f:
                quota_data = json.load(f)
                
            # Save quota data to database for historical tracking
            with sqlite3.connect(DB_PATH) as conn:
                cursor = conn.cursor()
                today = datetime.now().strftime('%Y-%m-%d')
                timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                
                if today in quota_data:
                    # Save overall usage
                    used = quota_data[today].get('used', 0)
                    remaining = quota_data[today].get('remaining', 10000)
                    
                    cursor.execute('''
                    INSERT INTO youtube_api_quota (
                        timestamp, date, used, remaining, operation, operation_count, operation_cost
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    ''', (timestamp, today, used, remaining, 'total', 0, 0))
                    
                    # Save operation-specific usage
                    operations = quota_data[today].get('operations', {})
                    for op_name, op_data in operations.items():
                        cursor.execute('''
                        INSERT INTO youtube_api_quota (
                            timestamp, date, used, remaining, operation, operation_count, operation_cost
                        ) VALUES (?, ?, ?, ?, ?, ?, ?)
                        ''', (timestamp, today, used, remaining, op_name, 
                              op_data.get('count', 0), op_data.get('cost', 0)))
                
                conn.commit()
                
            return quota_data
                
        except Exception as e:
            logger.error(f"Error reading YouTube API quota data: {str(e)}")
    
    return {}

# Add new function to get dynamic threshold data
def get_dynamic_thresholds():
    """Get dynamic view thresholds for channels."""
    try:
        video_history = VideoHistory()
        content_analyzer = ContentAnalyzer()
        
        # Get all channels from configuration files
        channels_data = {}
        
        # Check main channels.json
        main_config = get_channels_from_file()
        if 'channels' in main_config:
            for channel in main_config['channels']:
                # Remove @ if present
                clean_channel = channel[1:] if channel.startswith('@') else channel
                channels_data[clean_channel] = {'group': 'main'}
        
        # Check new format group files (channels-group.json)
        new_format_groups = ['sports', 'misc', 'films']
        for group in new_format_groups:
            group_file = os.path.join(os.path.dirname(__file__), f'channels-{group}.json')
            if os.path.exists(group_file):
                try:
                    with open(group_file, 'r') as f:
                        group_config = json.load(f)
                        if 'channels' in group_config:
                            for channel in group_config['channels']:
                                # For new format files, channels may be objects with username field
                                if isinstance(channel, dict) and 'username' in channel:
                                    username = channel['username']
                                else:
                                    username = channel
                                    
                                # Remove @ if present
                                clean_channel = username[1:] if username.startswith('@') else username
                                # Get publish days if available
                                publish_days = group_config.get('settings', {}).get('publish_days', [])
                                channels_data[clean_channel] = {
                                    'group': group,
                                    'publish_days': publish_days
                                }
                except Exception as e:
                    logger.error(f"Error reading channel group {group}: {str(e)}")
        
        # Check legacy group files (channelsA.json)
        legacy_groups = ['A', 'B', 'C']
        for group in legacy_groups:
            group_file = os.path.join(os.path.dirname(__file__), f'channels{group}.json')
            if os.path.exists(group_file):
                try:
                    with open(group_file, 'r') as f:
                        group_config = json.load(f)
                        if 'channels' in group_config:
                            for channel in group_config['channels']:
                                # Remove @ if present
                                clean_channel = channel[1:] if channel.startswith('@') else channel
                                # Get publish days if available
                                publish_days = group_config.get('settings', {}).get('publish_days', [])
                                channels_data[clean_channel] = {
                                    'group': group,
                                    'publish_days': publish_days
                                }
                except Exception as e:
                    logger.error(f"Error reading legacy channel group {group}: {str(e)}")
        
        # Get channel history for view analysis
        thresholds_data = []
        
        for channel, data in channels_data.items():
            history = video_history.get_channel_history(channel)
            if history:
                # Extract view counts
                view_counts = [int(video.get('metrics', {}).get('views', 0)) for video in history]
                view_counts = [views for views in view_counts if views > 0]
                
                if view_counts:
                    # Sort for percentiles
                    view_counts.sort()
                    
                    # Calculate statistics
                    avg_views = sum(view_counts) / len(view_counts)
                    median_views = view_counts[len(view_counts) // 2]
                    percentile_75_index = int(len(view_counts) * 0.75)
                    percentile_75 = view_counts[percentile_75_index] if percentile_75_index < len(view_counts) else median_views
                    
                    # Determine channel size
                    if avg_views < 20000:
                        channel_size = "small"
                        threshold = int(avg_views * 0.7)
                        min_bound = 3000
                    elif avg_views < 100000:
                        channel_size = "medium"
                        threshold = int(median_views * 0.8)
                        min_bound = 8000
                    else:
                        channel_size = "large"
                        threshold = int(percentile_75 * 0.7)
                        min_bound = 15000
                    
                    max_bound = 500000
                    threshold = max(min_bound, min(threshold, max_bound))
                    
                    # Add to database
                    with sqlite3.connect(DB_PATH) as conn:
                        cursor = conn.cursor()
                        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                        
                        cursor.execute('''
                        INSERT INTO dynamic_thresholds (
                            timestamp, channel, channel_size, avg_views, median_views, percentile_75, threshold
                        ) VALUES (?, ?, ?, ?, ?, ?, ?)
                        ''', (timestamp, channel, channel_size, int(avg_views), int(median_views), 
                              int(percentile_75), int(threshold)))
                        
                        conn.commit()
                    
                    # Add to return data
                    thresholds_data.append({
                        'channel': channel,
                        'group': data.get('group', 'main'),
                        'publish_days': data.get('publish_days', []),
                        'channel_size': channel_size,
                        'avg_views': int(avg_views),
                        'median_views': int(median_views),
                        'percentile_75': int(percentile_75),
                        'threshold': int(threshold)
                    })
        
        return thresholds_data
                
    except Exception as e:
        logger.error(f"Error calculating dynamic thresholds: {str(e)}")
        return []

# Add new function to get file cleanup statistics
def get_cleanup_stats():
    """Get statistics about file cleanup operations."""
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            
            # Get the most recent cleanup operations
            cursor.execute('''
            SELECT * FROM file_cleanup
            ORDER BY timestamp DESC
            LIMIT 10
            ''')
            
            cleanup_ops = cursor.fetchall()
            
            if cleanup_ops:
                # Convert to dictionaries
                columns = [col[0] for col in cursor.description]
                cleanup_data = [dict(zip(columns, row)) for row in cleanup_ops]
                
                # Calculate totals
                total_files = sum(op['files_removed'] for op in cleanup_data)
                total_space = sum(op['space_freed_mb'] for op in cleanup_data)
                
                return {
                    'operations': cleanup_data,
                    'total_files_removed': total_files,
                    'total_space_freed_mb': total_space
                }
            
            return {
                'operations': [],
                'total_files_removed': 0,
                'total_space_freed_mb': 0
            }
                
    except Exception as e:
        logger.error(f"Error getting cleanup statistics: {str(e)}")
        return {
            'operations': [],
            'total_files_removed': 0,
            'total_space_freed_mb': 0
        }

# Add new function to get channel groups
def get_channel_groups():
    """Get information about channel groups and their settings."""
    try:
        groups_data = {}
        
        # First check for new format files (channels-group.json)
        new_format_groups = ['sports', 'misc', 'films']
        for group in new_format_groups:
            group_file = os.path.join(os.path.dirname(__file__), f'channels-{group}.json')
            if os.path.exists(group_file):
                try:
                    with open(group_file, 'r') as f:
                        group_config = json.load(f)
                        if 'channels' in group_config and 'settings' in group_config:
                            channels = group_config['channels']
                            settings = group_config['settings']
                            
                            # Store group data
                            groups_data[group] = {
                                'channels': channels,
                                'publish_days': settings.get('publish_days', []),
                                'run_interval': settings.get('run_interval', 259200),
                                'last_run': None,  # Will be populated from logs if available
                                'next_run': None,  # Will be calculated below
                                'channel_count': len(channels)
                            }
                except Exception as e:
                    logger.error(f"Error reading channel group {group}: {str(e)}")
        
        # If no new format files found, check legacy format files
        if not groups_data:
            legacy_groups = ['A', 'B', 'C']
            for group in legacy_groups:
                group_file = os.path.join(os.path.dirname(__file__), f'channels{group}.json')
                if os.path.exists(group_file):
                    try:
                        with open(group_file, 'r') as f:
                            group_config = json.load(f)
                            if 'channels' in group_config and 'settings' in group_config:
                                channels = group_config['channels']
                                settings = group_config['settings']
                                
                                # Store group data
                                groups_data[group] = {
                                    'channels': channels,
                                    'publish_days': settings.get('publish_days', []),
                                    'run_interval': settings.get('run_interval', 259200),
                                    'last_run': None,  # Will be populated from logs if available
                                    'next_run': None,  # Will be calculated below
                                    'channel_count': len(channels)
                                }
                    except Exception as e:
                        logger.error(f"Error reading legacy channel group {group}: {str(e)}")
        
        # Try to determine last run times from the log file
        log_file = os.path.join(os.path.dirname(__file__), config.LOGGING['log_file'])
        if os.path.exists(log_file):
            try:
                with open(log_file, 'r') as f:
                    log_content = f.readlines()
                    
                    # Search for the last run of each group
                    for group in groups_data:
                        # Look for both new and old format log entries
                        search_terms = [
                            f"Using channel group {group} configuration",  # New format
                            f"Using channel group {group} configuration: channels-{group}.json",  # Explicit new format
                            f"Using legacy channel group {group} configuration: channels{group}.json"  # Legacy format
                        ]
                        
                        for line in reversed(log_content):  # Start from the end
                            if any(term in line for term in search_terms):
                                # Extract timestamp from the log line
                                timestamp_str = line.split(' - ')[0].strip()
                                try:
                                    last_run = datetime.strptime(timestamp_str, '%Y-%m-%d %H:%M:%S')
                                    groups_data[group]['last_run'] = last_run.strftime('%Y-%m-%d %H:%M:%S')
                                    
                                    # Calculate next run based on interval
                                    if 'run_interval' in groups_data[group]:
                                        interval_seconds = groups_data[group]['run_interval']
                                        next_run = last_run + timedelta(seconds=interval_seconds)
                                        groups_data[group]['next_run'] = next_run.strftime('%Y-%m-%d %H:%M:%S')
                                        
                                    break  # Found the most recent entry
                                except Exception as e:
                                    logger.error(f"Error parsing timestamp for group {group}: {str(e)}")
            except Exception as e:
                logger.error(f"Error reading log file for group run times: {str(e)}")
        
        # Save to database for history
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            
            for group, data in groups_data.items():
                channels_json = json.dumps(data['channels'])
                publish_days_json = json.dumps(data['publish_days'])
                
                cursor.execute('''
                INSERT INTO channel_groups (
                    timestamp, group_name, channels, publish_days, last_run, next_run
                ) VALUES (?, ?, ?, ?, ?, ?)
                ''', (timestamp, group, channels_json, publish_days_json, 
                      data.get('last_run'), data.get('next_run')))
            
            conn.commit()
            
        return groups_data
                
    except Exception as e:
        logger.error(f"Error getting channel groups: {str(e)}")
        return {}

# Add new function to record file cleanup operations
def record_cleanup_operation(directory, files_removed, space_freed_mb, retention_days):
    """Record a file cleanup operation in the database."""
    try:
        with sqlite3.connect(DB_PATH) as conn:
            cursor = conn.cursor()
            timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            
            cursor.execute('''
            INSERT INTO file_cleanup (
                timestamp, directory, files_removed, space_freed_mb, retention_days
            ) VALUES (?, ?, ?, ?, ?)
            ''', (timestamp, directory, files_removed, space_freed_mb, retention_days))
            
            conn.commit()
            
        logger.info(f"Recorded cleanup operation: {files_removed} files, {space_freed_mb:.2f} MB freed")
        return True
                
    except Exception as e:
        logger.error(f"Error recording cleanup operation: {str(e)}")
        return False

# Add new API routes for the enhanced features
@app.route('/api/quota')
def api_quota():
    """API endpoint for YouTube API quota information."""
    quota_data = get_youtube_api_quota()
    return jsonify(quota_data)

@app.route('/api/thresholds')
def api_thresholds():
    """API endpoint for dynamic view thresholds."""
    thresholds_data = get_dynamic_thresholds()
    return jsonify(thresholds_data)

@app.route('/api/cleanup')
def api_cleanup():
    """API endpoint for file cleanup statistics."""
    cleanup_data = get_cleanup_stats()
    return jsonify(cleanup_data)

@app.route('/api/groups')
def api_groups():
    """API endpoint for channel groups information."""
    groups_data = get_channel_groups()
    return jsonify(groups_data)

if __name__ == '__main__':
    run_dashboard(host='0.0.0.0', debug=True) 