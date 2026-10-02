<?php
header('Content-Type: application/json; charset=utf-8');
header('Access-Control-Allow-Origin: *');

$target_link = $url ?? ($_GET['url'] ?? '');

if (empty($target_link)) {
    http_response_code(400);
    echo json_encode([
        'success' => false,
        'error'   => 'URL parameter is missing',
        'hint'    => 'Use: /?url=https://youtu.be/VIDEO_ID'
    ], JSON_PRETTY_PRINT);
    exit;
}

if (!filter_var($target_link, FILTER_VALIDATE_URL)) {
    http_response_code(400);
    echo json_encode(['success' => false, 'error' => 'Invalid URL']);
    exit;
}

// Optional: sirf YouTube allow karo (security)
$host = strtolower(parse_url($target_link, PHP_URL_HOST) ?? '');
$allowed = ['youtube.com', 'www.youtube.com', 'youtu.be', 'm.youtube.com', 'music.youtube.com'];
if (!in_array($host, $allowed)) {
    http_response_code(400);
    echo json_encode(['success' => false, 'error' => 'Only YouTube URLs allowed']);
    exit;
}

// ============================================================
// CONFIG
// ============================================================
$YTDLP_BIN = '/usr/local/bin/yt-dlp';     // Docker me yahi path hai
$CACHE_DIR = sys_get_temp_dir();
$CACHE_TTL = 600;                          // 10 min
$TIMEOUT   = 45;

// ============================================================
// CACHE
// ============================================================
$cacheFile = $CACHE_DIR . '/yt_' . md5($target_link) . '.json';
if (file_exists($cacheFile) && (time() - filemtime($cacheFile)) < $CACHE_TTL) {
    readfile($cacheFile);
    exit;
}

// ============================================================
// BUILD CMD
// ============================================================
$cmd = escapeshellcmd($YTDLP_BIN)
     . ' --dump-json'
     . ' --no-warnings'
     . ' --no-playlist'
     . ' --skip-download'
     . ' --no-check-certificate'
     . ' --extractor-args "youtube:player_client=android,web"'
     . ' ' . escapeshellarg($target_link)
     . ' 2>&1';

// ============================================================
// RUN
// ============================================================
$descriptors = [
    0 => ['pipe', 'r'],
    1 => ['pipe', 'w'],
    2 => ['pipe', 'w'],
];

$process = proc_open($cmd, $descriptors, $pipes);

if (!is_resource($process)) {
    http_response_code(500);
    echo json_encode(['success' => false, 'error' => 'Failed to start yt-dlp']);
    exit;
}

fclose($pipes[0]);
stream_set_blocking($pipes[1], false);
stream_set_blocking($pipes[2], false);

$output = '';
$stderr = '';
$start  = time();

while (true) {
    $status = proc_get_status($process);
    $output .= stream_get_contents($pipes[1]);
    $stderr .= stream_get_contents($pipes[2]);

    if (!$status['running']) break;
    if ((time() - $start) > $TIMEOUT) {
        proc_terminate($process, 9);
        break;
    }
    usleep(100000);
}

$output .= stream_get_contents($pipes[1]);
$stderr .= stream_get_contents($pipes[2]);
fclose($pipes[1]);
fclose($pipes[2]);
proc_close($process);

// ============================================================
// PARSE
// ============================================================
$lines = preg_split('/\r?\n/', trim($output));
$jsonLine = null;
foreach (array_reverse($lines) as $line) {
    $line = trim($line);
    if ($line !== '' && $line[0] === '{') {
        $jsonLine = $line;
        break;
    }
}

if ($jsonLine === null) {
    http_response_code(500);
    echo json_encode([
        'success' => false,
        'error'   => 'No JSON from yt-dlp',
        'stderr'  => substr($stderr, 0, 800),
    ], JSON_PRETTY_PRINT);
    exit;
}

$yt = json_decode($jsonLine, true);
if (!is_array($yt)) {
    http_response_code(500);
    echo json_encode(['success' => false, 'error' => 'Invalid JSON']);
    exit;
}

// ============================================================
// NORMALIZE
// ============================================================
$media = [];
$duration = $yt['duration'] ?? 0;

if (!empty($yt['thumbnail'])) {
    $media[] = [
        'type' => 'photo', 'id' => 'thumbnail', 'url' => $yt['thumbnail'],
        'width' => null, 'height' => null, 'container' => 'image/jpeg',
        'has_audio' => false, 'has_video' => false, 'has_photo' => true,
        'quality' => 'Thumbnail',
    ];
}

if (!empty($yt['formats'])) {
    foreach ($yt['formats'] as $f) {
        $url = $f['url'] ?? '';
        if ($url === '') continue;

        $vcodec = $f['vcodec'] ?? 'none';
        $acodec = $f['acodec'] ?? 'none';
        $ext    = $f['ext'] ?? 'mp4';
        $height = $f['height'] ?? null;
        $abr    = $f['abr'] ?? null;

        if ($vcodec !== 'none') {
            $media[] = [
                'type' => 'video',
                'id'   => $f['format_id'] ?? null,
                'url'  => $url,
                'width' => $f['width'] ?? null,
                'height' => $height,
                'container' => 'video/' . ($ext === 'mp4' ? 'mp4' : $ext),
                'has_audio' => ($acodec !== 'none'),
                'has_video' => true,
                'has_photo' => false,
                'quality' => $height ? $height . 'p' : 'video',
                'duration' => $duration,
                'size' => $f['filesize'] ?? ($f['filesize_approx'] ?? null),
            ];
        } elseif ($acodec !== 'none') {
            $media[] = [
                'type' => 'audio',
                'id'   => $f['format_id'] ?? null,
                'url'  => $url,
                'width' => null, 'height' => null,
                'container' => 'audio/' . ($ext === 'm4a' ? 'mp4' : ($ext === 'mp3' ? 'mpeg' : $ext)),
                'has_audio' => true, 'has_video' => false, 'has_photo' => false,
                'quality' => $abr ? round($abr) . 'kbps' : 'audio',
                'duration' => $duration,
                'size' => $f['filesize'] ?? ($f['filesize_approx'] ?? null),
            ];
        }
    }
}

// Dedup
$seen = []; $unique = [];
foreach ($media as $item) {
    $key = strtolower(($item['type'] ?? '') . '|' . ($item['quality'] ?? ''));
    if (isset($seen[$key])) continue;
    $seen[$key] = true;
    $unique[] = $item;
}
$media = array_values($unique);

// Sort
$typeOrder = ['photo' => 1, 'video' => 2, 'audio' => 3];
usort($media, function ($a, $b) use ($typeOrder) {
    $aO = $typeOrder[strtolower($a['type'] ?? '')] ?? 99;
    $bO = $typeOrder[strtolower($b['type'] ?? '')] ?? 99;
    if ($aO !== $bO) return $aO <=> $bO;
    $aQ = (int) preg_replace('/\D/', '', $a['quality'] ?? '0');
    $bQ = (int) preg_replace('/\D/', '', $b['quality'] ?? '0');
    return $bQ <=> $aQ;
});

$response = [
    'success' => true,
    'type' => 'video',
    'id' => $yt['id'] ?? '',
    'username' => $yt['uploader'] ?? ($yt['channel'] ?? ''),
    'profile_image_uri' => $yt['thumbnail'] ?? '',
    'caption' => $yt['title'] ?? '',
    'media' => $media,
    'tags' => $yt['tags'] ?? [],
    'duration' => $duration,
    'width' => null,
    'height' => null,
    'errors' => [],
    'source' => 'render-yt-dlp',
];

$json = json_encode($response, JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE);
@file_put_contents($cacheFile, $json);
echo $json;
