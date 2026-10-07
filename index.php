<?php
declare(strict_types=1);

use Ytdlphp\Options;
use Ytdlphp\YtDlp;

// ... (Input validation from your original script) ...

// 1. Decode and write cookies from the environment variable
$cookiesB64 = getenv('YT_COOKIES_B64');
if ($cookiesB64 === false) {
    jsonOut(['success' => false, 'error' => 'Cookie environment variable not set.']);
}

$cookiesPath = '/tmp/cookies.txt';
if (file_put_contents($cookiesPath, base64_decode($cookiesB64)) === false) {
    jsonOut(['success' => false, 'error' => 'Failed to write cookies file.']);
}

// 2. Initialize yt-dlp with options
$ytDlp = new YtDlp();
$options = Options::create()
    ->cookies($cookiesPath) // Use the cookies file
    ->format('bestvideo+bestaudio/best')
    ->output('/tmp/%(title)s.%(ext)s'); // Use /tmp for temporary files

try {
    // 3. Extract info or download
    $info = $ytDlp->extractInfo($url, $options);
    // ... (Your logic to handle download/metadata)
} catch (\Exception $e) {
    jsonOut(['success' => false, 'error' => 'yt-dlp failed: ' . $e->getMessage()]);
}
