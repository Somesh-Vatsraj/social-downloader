// ============================================================
// DEBUG MODE — /?debug=1
// ============================================================
if (isset($_GET['debug'])) {
    header('Content-Type: text/plain; charset=utf-8');
    
    echo "PHP version: " . PHP_VERSION . "\n";
    echo "OS: " . PHP_OS . "\n\n";
    
    // yt-dlp version
    echo "=== yt-dlp version ===\n";
    echo shell_exec('/usr/local/bin/yt-dlp --version 2>&1') . "\n";
    
    // yt-dlp --verbose on test URL
    echo "=== yt-dlp verbose test ===\n";
    $testUrl = $_GET['url'] ?? 'https://youtu.be/2aMVhBNhAgQ';
    $cmd = '/usr/local/bin/yt-dlp --dump-json --no-warnings --no-playlist --skip-download '
         . '--no-check-certificate -v ' . escapeshellarg($testUrl) . ' 2>&1';
    echo "CMD: $cmd\n\n";
    echo shell_exec($cmd);
    exit;
}
