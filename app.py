import os
import base64
import logging
from flask import Flask, request, jsonify, Response, stream_with_context
from flask_cors import CORS
import yt_dlp
import requests

# --- Configuration ---
app = Flask(__name__)
CORS(app)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Path for the cookies file (written from environment variable)
COOKIES_FILE_PATH = '/tmp/cookies.txt'

# --- Helper: Write Cookies from Environment Variable ---
def setup_cookies():
    """
    Decodes the base64-encoded cookies from the Render environment variable
    and writes them to a temporary file for yt-dlp to use.
    """
    cookies_b64 = os.environ.get('YT_COOKIES_B64')
    if cookies_b64:
        try:
            with open(COOKIES_FILE_PATH, 'wb') as f:
                f.write(base64.b64decode(cookies_b64))
            logger.info("Cookies file written successfully from environment variable.")
        except Exception as e:
            logger.error(f"Failed to write cookies file: {e}")
    else:
        logger.warning("YT_COOKIES_B64 environment variable not set. Downloads may be rate-limited.")

# --- yt-dlp Options ---
def get_ydl_opts(format_id=None, download=False):
    """
    Returns a dictionary of options for yt-dlp.
    Configures the PO Token provider, cookies, and the client to use.
    """
    opts = {
        'quiet': True,
        'no_warnings': True,
        'extract_flat': False,
        # Use cookies if the file exists
        'cookiefile': COOKIES_FILE_PATH if os.path.exists(COOKIES_FILE_PATH) else None,
        
        # Use the PO Token Provider HTTP server
        # The server runs on localhost:4416 inside the Docker container.
        'extractor_args': {
            'youtube': {
                'player_client': ['web', 'mweb'],  # Use web clients
                'pot_provider_url': 'http://127.0.0.1:4416', # This tells yt-dlp where to find the provider
            }
        },
        # Specify a format if one is requested
        'format': format_id if format_id else 'bestvideo+bestaudio/best',
    }
    
    if download:
        opts['outtmpl'] = '-'
        opts['logtostderr'] = True
    return opts

# --- Flask Routes ---

@app.route('/health', methods=['GET'])
def health_check():
    """Simple health check endpoint."""
    return jsonify({'status': 'ok', 'service': 'youtube-downloader'})

@app.route('/info', methods=['GET'])
def get_video_info():
    """
    Endpoint to get metadata and available formats for a video.
    Usage: /info?url=YOUR_YOUTUBE_URL
    """
    video_url = request.args.get('url')
    if not video_url:
        return jsonify({'success': False, 'error': 'Missing "url" parameter'}), 400

    try:
        with yt_dlp.YoutubeDL(get_ydl_opts()) as ydl:
            info_dict = ydl.extract_info(video_url, download=False)
            
            # Extract relevant format information
            formats = []
            for f in info_dict.get('formats', []):
                formats.append({
                    'format_id': f.get('format_id'),
                    'ext': f.get('ext'),
                    'resolution': f.get('resolution') or f.get('format_note'),
                    'filesize': f.get('filesize') or f.get('filesize_approx'),
                    'vcodec': f.get('vcodec'),
                    'acodec': f.get('acodec'),
                    'note': f.get('format_note'),
                })

            return jsonify({
                'success': True,
                'title': info_dict.get('title'),
                'thumbnail': info_dict.get('thumbnail'),
                'duration': info_dict.get('duration'),
                'uploader': info_dict.get('uploader'),
                'formats': formats
            })
    except Exception as e:
        logger.error(f"Error extracting info: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/download', methods=['GET'])
def download_video():
    """
    Endpoint to stream a video/audio download.
    Usage: /download?url=YOUR_YOUTUBE_URL&format_id=FORMAT_ID
    """
    video_url = request.args.get('url')
    format_id = request.args.get('format_id') # Optional: specify a format ID

    if not video_url:
        return jsonify({'success': False, 'error': 'Missing "url" parameter'}), 400

    try:
        # We use a separate ydl instance for downloading to stream output.
        ydl_opts = get_ydl_opts(format_id=format_id, download=True)
        
        # This function acts as a generator for the streaming response.
        def generate():
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                # yt-dlp will write the video data to stdout (which is our generator)
                ydl.download([video_url])

        # Create a streaming response
        # Note: yt-dlp's default output to stdout is binary data.
        return Response(stream_with_context(generate()), content_type='application/octet-stream')
        
    except Exception as e:
        logger.error(f"Error during download: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

# --- Main Execution ---
if __name__ == '__main__':
    # Write cookies on startup
    setup_cookies()
    
    # Run the Flask app. Render provides the PORT environment variable.
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
