<?php
// Render pe PHP built-in server ko route karne ke liye
$uri = parse_url($_SERVER['REQUEST_URI'], PHP_URL_PATH);

// Health check
if ($uri === '/health') {
    header('Content-Type: application/json');
    echo json_encode(['status' => 'ok', 'time' => time()]);
    exit;
}

// Favicon skip
if ($uri === '/favicon.ico') {
    http_response_code(204);
    exit;
}

// Baaki sab index.php ko
require __DIR__ . '/index.php';
