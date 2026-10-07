<?php

header("Content-Type: application/json; charset=utf-8");


/*
|--------------------------------------------------------------------------
| Read JSON
|--------------------------------------------------------------------------
*/

$input = file_get_contents("php://input");

$data = json_decode($input, true);


if (!is_array($data)) {

    echo json_encode([
        "success" => false,
        "error" => "Invalid request."
    ]);

    exit;
}


/*
|--------------------------------------------------------------------------
| Get values
|--------------------------------------------------------------------------
*/

$url = trim($data["url"] ?? "");

$format = $data["format"] ?? "best";


/*
|--------------------------------------------------------------------------
| Validate URL
|--------------------------------------------------------------------------
*/

if ($url === "") {

    echo json_encode([
        "success" => false,
        "error" => "Video URL is required."
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
| Supported formats
|--------------------------------------------------------------------------
*/

$allowedFormats = [
    "best",
    "720",
    "480",
    "360",
    "audio"
];


if (!in_array($format, $allowedFormats, true)) {

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

$downloadDir =
    __DIR__ . "/downloads";


if (!is_dir($downloadDir)) {

    if (!mkdir($downloadDir, 0755, true)) {

        echo json_encode([
            "success" => false,
            "error" =>
                "Could not create download directory."
        ]);

        exit;
    }
}


/*
|--------------------------------------------------------------------------
| Generate unique filename
|--------------------------------------------------------------------------
*/

$fileId =
    "video_" .
    bin2hex(random_bytes(8));


$outputTemplate =
    $downloadDir .
    "/" .
    $fileId .
    ".%(ext)s";


/*
|--------------------------------------------------------------------------
| Select yt-dlp format
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

        break;
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
    escapeshellarg($outputTemplate);


/*
|--------------------------------------------------------------------------
| yt-dlp command
|--------------------------------------------------------------------------
|
| Deno is explicitly selected as the JS runtime.
|
*/

$command =
    "yt-dlp " .

    "--no-playlist " .

    "--js-runtimes deno " .

    "--format " .
    $safeFormat .
    " " .

    "--output " .
    $safeOutput .
    " " .

    "--no-warnings " .

    $safeUrl .

    " 2>&1";


/*
|--------------------------------------------------------------------------
| Execute
|--------------------------------------------------------------------------
*/

$outputLines = [];

$returnCode = 0;


exec(
    $command,
    $outputLines,
    $returnCode
);


/*
|--------------------------------------------------------------------------
| Find downloaded file
|--------------------------------------------------------------------------
*/

$files =
    glob(
        $downloadDir .
        "/" .
        $fileId .
        ".*"
    );


/*
|--------------------------------------------------------------------------
| Handle yt-dlp error
|--------------------------------------------------------------------------
*/

if (
    $returnCode !== 0 ||
    empty($files)
) {

    $error =
        implode(
            "\n",
            $outputLines
        );


    if ($error === "") {

        $error =
            "yt-dlp download failed.";
    }


    echo json_encode([
        "success" => false,
        "error" => $error
    ]);

    exit;
}


/*
|--------------------------------------------------------------------------
| Get file
|--------------------------------------------------------------------------
*/

$filePath =
    $files[0];


$fileName =
    basename($filePath);


/*
|--------------------------------------------------------------------------
| Return download URL
|--------------------------------------------------------------------------
*/

$fileUrl =
    "downloads/" .
    rawurlencode($fileName);


echo json_encode([

    "success" => true,

    "url" => $fileUrl

]);

exit;