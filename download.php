<?php

header("Content-Type: application/json; charset=utf-8");


/*
|--------------------------------------------------------------------------
| Read request
|--------------------------------------------------------------------------
*/

$raw =
    file_get_contents("php://input");

$data =
    json_decode($raw, true);

if (!is_array($data)) {

    echo json_encode([
        "success" => false,
        "error" => "Invalid request."
    ]);

    exit;
}


$url =
    trim($data["url"] ?? "");

$format =
    $data["format"] ?? "best";


/*
|--------------------------------------------------------------------------
| Validate URL
|--------------------------------------------------------------------------
*/

if ($url === "") {

    echo json_encode([
        "success" => false,
        "error" => "URL is required."
    ]);

    exit;
}

if (!filter_var($url, FILTER_VALIDATE_URL)) {

    echo json_encode([
        "success" => false,
        "error" => "Invalid URL."
    ]);

    exit;
}


/*
|--------------------------------------------------------------------------
| Allowed formats
|--------------------------------------------------------------------------
*/

$allowed = [
    "best",
    "720",
    "480",
    "360",
    "audio"
];

if (!in_array($format, $allowed, true)) {

    echo json_encode([
        "success" => false,
        "error" => "Invalid format."
    ]);

    exit;
}


/*
|--------------------------------------------------------------------------
| Download directory
|--------------------------------------------------------------------------
*/

$dir =
    __DIR__ . "/downloads";

if (!is_dir($dir)) {

    mkdir($dir, 0755, true);
}


/*
|--------------------------------------------------------------------------
| Unique filename
|--------------------------------------------------------------------------
*/

$id =
    "video_" .
    bin2hex(random_bytes(8));

$output =
    $dir . "/" .
    $id .
    ".%(ext)s";


/*
|--------------------------------------------------------------------------
| Select format
|--------------------------------------------------------------------------
*/

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

        $formatArg =
            "bestaudio";

        break;

    default:

        $formatArg =
            "bestvideo+bestaudio/best";
}


/*
|--------------------------------------------------------------------------
| Escape shell arguments
|--------------------------------------------------------------------------
*/

$safeUrl =
    escapeshellarg($url);

$safeFormat =
    escapeshellarg($formatArg);

$safeOutput =
    escapeshellarg($output);


/*
|--------------------------------------------------------------------------
| Run yt-dlp
|--------------------------------------------------------------------------
*/

$command =
    "yt-dlp " .
    "--no-playlist " .
    "--js-runtimes deno " .
    "--format " . $safeFormat . " " .
    "--output " . $safeOutput . " " .
    $safeUrl .
    " 2>&1";


$outputLines = [];

$returnCode = 0;

exec(
    $command,
    $outputLines,
    $returnCode
);


/*
|--------------------------------------------------------------------------
| Find file
|--------------------------------------------------------------------------
*/

$files =
    glob($dir . "/" . $id . ".*");


/*
|--------------------------------------------------------------------------
| Error
|--------------------------------------------------------------------------
*/

if (
    $returnCode !== 0 ||
    empty($files)
) {

    $error =
        implode("\n", $outputLines);

    if ($error === "") {
        $error = "yt-dlp failed.";
    }

    echo json_encode([
        "success" => false,
        "error" => $error
    ]);

    exit;
}


/*
|--------------------------------------------------------------------------
| Return file URL
|--------------------------------------------------------------------------
*/

$file =
    basename($files[0]);

$url =
    "downloads/" .
    rawurlencode($file);


echo json_encode([
    "success" => true,
    "url" => $url
]);

exit;