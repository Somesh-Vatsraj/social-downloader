<?php

header("Content-Type: application/json; charset=utf-8");

function response($data)
{
    echo json_encode($data, JSON_UNESCAPED_UNICODE);
    exit;
}

// Read request
$raw = file_get_contents("php://input");
$data = json_decode($raw, true);

if (!is_array($data)) {
    response([
        "success" => false,
        "error" => "Invalid request."
    ]);
}

$url = trim($data["url"] ?? "");
$format = $data["format"] ?? "best";

// Validate URL
if ($url === "") {
    response([
        "success" => false,
        "error" => "Please enter a video URL."
    ]);
}

if (!filter_var($url, FILTER_VALIDATE_URL)) {
    response([
        "success" => false,
        "error" => "Invalid URL."
    ]);
}

// Allowed formats
$allowedFormats = [
    "best",
    "720",
    "480",
    "360",
    "audio"
];

if (!in_array($format, $allowedFormats, true)) {
    response([
        "success" => false,
        "error" => "Invalid format."
    ]);
}

// Download directory
$downloadDir = __DIR__ . "/downloads";

if (!is_dir($downloadDir)) {
    if (!mkdir($downloadDir, 0755, true)) {
        response([
            "success" => false,
            "error" => "Cannot create download directory."
        ]);
    }
}

// Unique ID
$id = "video_" . bin2hex(random_bytes(8));

// Output template
$outputTemplate = $downloadDir . "/" . $id . ".%(ext)s";

// Format selection
switch ($format) {

    case "720":
        $formatArg =
            "bestvideo[height<=720]+bestaudio/" .
            "best[height<=720]";
        break;

    case "480":
        $formatArg =
            "bestvideo[height<=480]+bestaudio/" .
            "best[height<=480]";
        break;

    case "360":
        $formatArg =
            "bestvideo[height<=360]+bestaudio/" .
            "best[height<=360]";
        break;

    case "audio":
        $formatArg = "bestaudio";
        break;

    default:
        $formatArg =
            "bestvideo+bestaudio/best";
        break;
}

// Deno path
$denoPath = "/root/.deno/bin/deno";

// Escape shell arguments
$safeUrl = escapeshellarg($url);
$safeFormat = escapeshellarg($formatArg);
$safeOutput = escapeshellarg($outputTemplate);
$safeDeno = escapeshellarg("deno:" . $denoPath);

// Build yt-dlp command
$command =
    "yt-dlp " .
    "--no-playlist " .
    "--js-runtimes " . $safeDeno . " " .
    "--format " . $safeFormat . " " .
    "--output " . $safeOutput . " " .
    $safeUrl .
    " 2>&1";

// Execute
$outputLines = [];
$returnCode = 0;

exec($command, $outputLines, $returnCode);

// Find output files
$files = glob($downloadDir . "/" . $id . ".*");

// Failure
if ($returnCode !== 0 || empty($files)) {

    $error = implode("\n", $outputLines);

    if ($error === "") {
        $error = "yt-dlp failed.";
    }

    response([
        "success" => false,
        "error" => $error
    ]);
}

// Select first file
$file = $files[0];

if (!file_exists($file)) {
    response([
        "success" => false,
        "error" => "Downloaded file was not found."
    ]);
}

// Filename
$fileName = basename($file);

// Public URL
$fileUrl = "downloads/" . rawurlencode($fileName);

// Success
response([
    "success" => true,
    "url" => $fileUrl,
    "filename" => $fileName
]);