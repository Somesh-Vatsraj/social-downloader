<!DOCTYPE html>
<html>
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
            display: flex;
            justify-content: center;
            align-items: center;
            background: #f3f4f6;
        }

        .box {
            width: 92%;
            max-width: 500px;
            background: white;
            padding: 25px;
            border-radius: 15px;
            box-shadow: 0 8px 30px rgba(0,0,0,.10);
        }

        h1 {
            text-align: center;
            margin-top: 0;
        }

        input, select, button {
            width: 100%;
            padding: 13px;
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

        button:hover {
            background: #000;
        }

        #result {
            margin-top: 15px;
            text-align: center;
            word-break: break-word;
        }

        a {
            display: inline-block;
            margin-top: 10px;
            padding: 11px 18px;
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
        required
    >

    <select id="format">
        <option value="best">Best Quality</option>
        <option value="720">720p</option>
        <option value="480">480p</option>
        <option value="360">360p</option>
        <option value="audio">Audio</option>
    </select>

    <button onclick="downloadVideo()">
        Download
    </button>

    <div id="result"></div>
</div>

<script>
async function downloadVideo() {

    const url = document.getElementById("url").value.trim();
    const format = document.getElementById("format").value;
    const result = document.getElementById("result");

    if (!url) {
        result.innerHTML = "Please enter a video URL.";
        return;
    }

    result.innerHTML = "Processing...";

    try {

        const response = await fetch("download.php", {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify({
                url: url,
                format: format
            })
        });

        const data = await response.json();

        if (data.success) {

            result.innerHTML =
                `<a href="${data.url}" download>
                    Download File
                </a>`;

        } else {

            result.innerHTML =
                "Error: " + (data.error || "Download failed.");

        }

    } catch (error) {

        result.innerHTML =
            "Server error. Please try again.";

    }
}
</script>

</body>
</html>