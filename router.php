<?php
$uri = parse_url($_SERVER['REQUEST_URI'], PHP_URL_PATH);

if ($uri === '/health') {
    header('Content-Type: application/json');
    echo json_encode(['status' => 'ok', 'time' => time()]);
    exit;
}

if ($uri === '/favicon.ico') {
    http_response_code(204);
    exit;
}

require __DIR__ . '/index.php';
