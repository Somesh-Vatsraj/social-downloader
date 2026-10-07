<?php

header("Content-Type: application/json");

$data = json_decode(file_get_contents("php://input"), true);

$url = trim($data["url"] ?? "");
$format = $data["format"] ?? "best";

if ($url === "") {
    echo json_encode([
        "success" => false,
        "error" => "Video URL is required."
    ]);
    exit;
}

/*
 * Basic URL validation.
 * Add other platforms only if you specifically want
 * to support them and their terms permit downloading.
 */

if (!filter_var($url, FILTER_VALIDATE_URL)) {
    echo json_encode([
        "success" => false,
        "error" => "Invalid URL."
    ]);
    exit;
}

$downloadDir = __DIR__ . "/downloads";

if (!is_dir($downloadDir)) {
    mkdir($downloadDir, 0755, true);
}

$filename = "video_" . bin2hex(random_bytes(6));

$output = $downloadDir . "/" . $filename . ".%(ext)s";

/*
 * Select format.
 */

switch ($format) {

    case "720":
        $formatArg = "bestvideo[height<=720]+bestaudio/best[height<=720]";
        break;

    case "480":
        $formatArg = "bestvideo[height<=480]+bestaudio/best[height<=480]";
        break;

    case "360":
        $formatArg = "bestvideo[height<=360]+bestaudio/best[height<=360]";
        break;

    case "audio":
        $formatArg = "bestaudio";
        break;

    default:
        $formatArg = "bestvideo+bestaudio/best";
        break;
}

/*
 * Escape shell arguments.
 */

$safeUrl = escapeshellarg($url);
$safeOutput = escapeshellarg($output);
$safeFormat = escapeshellarg($formatArg);

$command =
    "yt-dlp " .
    "--no-playlist " .
    "-f " . $safeFormat . " " .
    "-o " . $safeOutput . " " .
    $safeUrl .
    " 2>&1";

exec($command, $outputLines, $returnCode);

if ($returnCode !== 0) {

    echo json_encode([
        "success" => false,
        "error" => implode("\n", $outputLines)
    ]);

    exit;
}

/*
 * Find generated file.
 */

$files = glob($downloadDir . "/" . $filename . ".*");

if (!$files) {

    echo json_encode([
        "success" => false,
        "error" => "Downloaded file was not found."
    ]);

    exit;
}

$file = basename($files[0]);

echo json_encode([
    "success" => true,
    "url" => "downloads/" . rawurlencode($file)
]);