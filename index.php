<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">

<title>Video Downloader</title>

<style>
* {
    box-sizing: border-box;
    font-family: Arial, sans-serif;
}

body {
    margin: 0;
    min-height: 100vh;
    background: #f3f4f6;
    display: flex;
    align-items: center;
    justify-content: center;
}

.box {
    width: 92%;
    max-width: 500px;
    background: white;
    padding: 25px;
    border-radius: 16px;
    box-shadow: 0 10px 35px rgba(0,0,0,.10);
}

h1 {
    text-align: center;
}

input,
select,
button {
    width: 100%;
    padding: 14px;
    margin-top: 12px;
    border-radius: 8px;
    border: 1px solid #ddd;
    font-size: 15px;
}

button {
    background: #111827;
    color: white;
    border: 0;
    cursor: pointer;
}

button:disabled {
    background: #888;
}

#result {
    margin-top: 18px;
    text-align: center;
    white-space: pre-wrap;
    word-break: break-word;
}

.error {
    color: #dc2626;
}

.success {
    color: #15803d;
}

.download {
    display: inline-block;
    margin-top: 12px;
    padding: 12px 20px;
    background: #16a34a;
    color: white;
    text-decoration: none;
    border-radius: 8px;
}
</style>
</head>

<body>

<div class="box">

<h1>Video Downloader</h1>

<input
    type="url"
    id="url"
    placeholder="Paste public video URL"
>

<select id="format">
    <option value="best">Best Quality</option>
    <option value="720">720p</option>
    <option value="480">480p</option>
    <option value="360">360p</option>
    <option value="audio">Audio</option>
</select>

<button id="btn" onclick="downloadVideo()">
    Download
</button>

<div id="result"></div>

</div>

<script>
async function downloadVideo() {

    const url =
        document.getElementById("url").value.trim();

    const format =
        document.getElementById("format").value;

    const btn =
        document.getElementById("btn");

    const result =
        document.getElementById("result");

    if (!url) {
        result.className = "error";
        result.textContent = "Please enter a URL.";
        return;
    }

    btn.disabled = true;
    btn.textContent = "Processing...";

    result.className = "";
    result.textContent = "Downloading...";

    try {

        const response = await fetch(
            "download.php",
            {
                method: "POST",
                headers: {
                    "Content-Type": "application/json"
                },
                body: JSON.stringify({
                    url: url,
                    format: format
                })
            }
        );

        const data = await response.json();

        if (data.success) {

            result.className = "success";

            result.innerHTML =
                "Download ready.<br>" +
                '<a class="download" href="' +
                data.url +
                '" download>Download File</a>';

        } else {

            result.className = "error";
            result.textContent =
                data.error || "Download failed.";

        }

    } catch (error) {

        result.className = "error";
        result.textContent =
            "Server connection error.";

    }

    btn.disabled = false;
    btn.textContent = "Download";
}
</script>

</body>
</html>