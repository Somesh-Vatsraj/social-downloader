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

        .container {
            width: 92%;
            max-width: 500px;

            background: #ffffff;
            padding: 25px;

            border-radius: 16px;

            box-shadow:
                0 10px 35px rgba(0,0,0,0.10);
        }

        h1 {
            text-align: center;
            margin-top: 0;
            margin-bottom: 20px;
        }

        input,
        select,
        button {
            width: 100%;
            padding: 14px;

            margin-top: 12px;

            border-radius: 9px;
            border: 1px solid #d1d5db;

            font-size: 15px;
        }

        input:focus,
        select:focus {
            outline: none;
            border-color: #111827;
        }

        button {
            background: #111827;
            color: white;

            border: none;

            cursor: pointer;
            font-weight: bold;
        }

        button:hover {
            background: #000000;
        }

        button:disabled {
            background: #9ca3af;
            cursor: not-allowed;
        }

        #result {
            margin-top: 18px;
            text-align: center;
            word-break: break-word;
        }

        .success {
            color: #15803d;
        }

        .error {
            color: #dc2626;
            font-size: 14px;
            white-space: pre-wrap;
        }

        .loading {
            color: #374151;
        }

        .download-btn {
            display: inline-block;

            margin-top: 12px;
            padding: 12px 20px;

            background: #16a34a;
            color: white;

            text-decoration: none;
            border-radius: 9px;
        }
    </style>
</head>

<body>

<div class="container">

    <h1>Video Downloader</h1>

    <input
        type="url"
        id="url"
        placeholder="Paste public video URL"
        autocomplete="off"
    >

    <select id="format">

        <option value="best">
            Best Quality
        </option>

        <option value="720">
            720p
        </option>

        <option value="480">
            480p
        </option>

        <option value="360">
            360p
        </option>

        <option value="audio">
            Audio
        </option>

    </select>

    <button id="downloadButton" onclick="downloadVideo()">
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

    const button =
        document.getElementById("downloadButton");

    const result =
        document.getElementById("result");


    if (!url) {

        result.className = "error";
        result.textContent =
            "Please enter a video URL.";

        return;
    }


    button.disabled = true;

    button.textContent = "Processing...";

    result.className = "loading";

    result.textContent =
        "Getting video information...";


    try {

        const response = await fetch(
            "download.php",
            {
                method: "POST",

                headers: {
                    "Content-Type":
                        "application/json"
                },

                body: JSON.stringify({
                    url: url,
                    format: format
                })
            }
        );


        const data =
            await response.json();


        if (data.success) {

            result.className = "success";

            result.innerHTML =
                `
                Download ready.<br>

                <a
                    class="download-btn"
                    href="${data.url}"
                    download
                >
                    Download File
                </a>
                `;

        } else {

            result.className = "error";

            result.textContent =
                data.error ||
                "Download failed.";

        }

    } catch (error) {

        result.className = "error";

        result.textContent =
            "Server error. Please try again.";

    }


    button.disabled = false;

    button.textContent = "Download";
}

</script>

</body>
</html>