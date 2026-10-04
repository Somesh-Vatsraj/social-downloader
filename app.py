import os
import uuid
import shutil
import subprocess
import time
import requests
from pathlib import Path

import gradio as gr
from faster_whisper import WhisperModel
from gtts import gTTS


# ============================================================
# CONFIG
# ============================================================

BASE_DIR = Path("/tmp/chinese_hindi")
OUTPUT_DIR = BASE_DIR / "outputs"

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

WHISPER_MODEL_NAME = "tiny"

whisper_model = None


# ============================================================
# WHISPER MODEL
# ============================================================

def get_whisper_model():

    global whisper_model

    if whisper_model is None:

        print("================================")
        print("Loading Whisper tiny model...")
        print("================================")

        whisper_model = WhisperModel(
            WHISPER_MODEL_NAME,
            device="cpu",
            compute_type="int8",
            cpu_threads=1,
            num_workers=1
        )

        print("Whisper model loaded.")

    return whisper_model


# ============================================================
# RUN COMMAND
# ============================================================

def run_command(command):

    print(
        "RUN:",
        " ".join(str(x) for x in command)
    )

    result = subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )

    if result.returncode != 0:

        print(result.stderr)

        raise RuntimeError(
            result.stderr[-5000:]
        )

    return result


# ============================================================
# VIDEO DURATION
# ============================================================

def get_video_duration(video):

    result = run_command([
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(video)
    ])

    return float(result.stdout.strip())


# ============================================================
# EXTRACT AUDIO
# ============================================================

def extract_audio(video, audio):

    run_command([
        "ffmpeg",
        "-y",
        "-i",
        str(video),
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-c:a",
        "pcm_s16le",
        str(audio)
    ])


# ============================================================
# CHINESE TRANSCRIPTION
# ============================================================

def transcribe_chinese(audio, progress):

    model = get_whisper_model()

    print("Starting Chinese transcription...")

    segments, info = model.transcribe(
        str(audio),
        language="zh",
        beam_size=1,
        best_of=1,
        temperature=0,
        vad_filter=True,
        condition_on_previous_text=False
    )

    results = []

    count = 0

    for segment in segments:

        text = segment.text.strip()

        if not text:
            continue

        results.append({
            "start": float(segment.start),
            "end": float(segment.end),
            "text": text
        })

        count += 1

        progress(
            0.20,
            desc=f"Chinese speech: {count}"
        )

    print("Segments:", len(results))

    return results


# ============================================================
# MYMEMORY TRANSLATION
# ============================================================

def translate_mymemory(text):

    url = "https://api.mymemory.translated.net/get"

    params = {
        "q": text,
        "langpair": "zh-CN|hi"
    }

    response = requests.get(
        url,
        params=params,
        timeout=30
    )

    response.raise_for_status()

    data = response.json()

    response_data = data.get(
        "responseData",
        {}
    )

    translated = response_data.get(
        "translatedText"
    )

    if not translated:
        raise RuntimeError(
            "MyMemory returned empty translation."
        )

    return translated.strip()


# ============================================================
# GOOGLE TRANSLATE WEB FALLBACK
# ============================================================

def translate_google_fallback(text):

    import urllib.parse

    encoded = urllib.parse.quote(text)

    url = (
        "https://translate.googleapis.com/"
        "translate_a/single"
        "?client=gtx"
        "&sl=zh-CN"
        "&tl=hi"
        "&dt=t"
        f"&q={encoded}"
    )

    response = requests.get(
        url,
        timeout=30,
        headers={
            "User-Agent": "Mozilla/5.0"
        }
    )

    response.raise_for_status()

    data = response.json()

    translated_parts = []

    if isinstance(data, list) and len(data) > 0:

        parts = data[0]

        if isinstance(parts, list):

            for part in parts:

                if (
                    isinstance(part, list)
                    and len(part) > 0
                    and part[0]
                ):
                    translated_parts.append(
                        str(part[0])
                    )

    translated = "".join(
        translated_parts
    ).strip()

    if not translated:

        raise RuntimeError(
            "Google returned empty translation."
        )

    return translated


# ============================================================
# TRANSLATE SINGLE TEXT
# ============================================================

def translate_single_text(text):

    text = text.strip()

    if not text:
        return ""

    # --------------------------------------------------------
    # FIRST: MYMEMORY
    # --------------------------------------------------------

    try:

        print(
            "Trying MyMemory translation..."
        )

        result = translate_mymemory(text)

        if result:
            return result

    except Exception as e:

        print(
            "MyMemory error:",
            e
        )

    # --------------------------------------------------------
    # SECOND: GOOGLE FALLBACK
    # --------------------------------------------------------

    try:

        print(
            "Trying Google fallback..."
        )

        result = translate_google_fallback(
            text
        )

        if result:
            return result

    except Exception as e:

        print(
            "Google fallback error:",
            e
        )

    return ""


# ============================================================
# CHINESE -> HINDI
# ============================================================

def translate_to_hindi(
    segments,
    progress
):

    print("Starting translation...")

    results = []

    total = len(segments)

    if total == 0:
        return []

    # Free Whisper memory before translation
    global whisper_model

    whisper_model = None

    import gc

    gc.collect()

    # --------------------------------------------------------
    # TRANSLATE
    # --------------------------------------------------------

    for index, segment in enumerate(segments):

        chinese_text = segment["text"].strip()

        if not chinese_text:
            continue

        print(
            f"Translating "
            f"{index + 1}/{total}: "
            f"{chinese_text[:100]}"
        )

        hindi_text = ""

        for attempt in range(2):

            hindi_text = translate_single_text(
                chinese_text
            )

            if hindi_text:
                break

            wait = 2 + (attempt * 3)

            print(
                f"Translation retry "
                f"in {wait} seconds..."
            )

            time.sleep(wait)

        if hindi_text:

            results.append({
                "start": segment["start"],
                "end": segment["end"],
                "text": hindi_text
            })

        else:

            print(
                "Translation failed for segment:",
                index + 1
            )

        progress(
            0.25 + (
                0.20 *
                (
                    (index + 1)
                    /
                    max(total, 1)
                )
            ),
            desc=(
                f"Translation "
                f"{index + 1}/{total}"
            )
        )

        # Prevent rate limiting
        time.sleep(0.8)

    print(
        "Hindi segments:",
        len(results)
    )

    return results


# ============================================================
# HINDI TTS
# ============================================================

def make_voice(
    text,
    output_file
):

    tts = gTTS(
        text=text,
        lang="hi",
        slow=False
    )

    tts.save(
        str(output_file)
    )


# ============================================================
# CREATE HINDI AUDIO
# ============================================================

def create_hindi_audio(
    segments,
    duration,
    output_audio,
    job_dir,
    progress
):

    if not segments:

        raise RuntimeError(
            "No Hindi text available."
        )

    voice_files = []

    total = len(segments)

    print("Creating Hindi voice...")

    for index, segment in enumerate(segments):

        text = segment["text"].strip()

        if not text:
            continue

        voice_file = (
            job_dir /
            f"voice_{index}.mp3"
        )

        try:

            make_voice(
                text,
                voice_file
            )

            voice_files.append({
                "file": voice_file,
                "start": segment["start"]
            })

        except Exception as e:

            print(
                "Voice error:",
                e
            )

        progress(
            0.45 + (
                0.25 *
                (
                    (index + 1)
                    /
                    max(total, 1)
                )
            ),
            desc=(
                f"Hindi voice "
                f"{index + 1}/{total}"
            )
        )

    if not voice_files:

        raise RuntimeError(
            "Hindi voice generation failed."
        )

    # --------------------------------------------------------
    # FFMPEG AUDIO
    # --------------------------------------------------------

    command = [
        "ffmpeg",
        "-y"
    ]

    for item in voice_files:

        command.extend([
            "-i",
            str(item["file"])
        ])

    filters = []

    for index, item in enumerate(voice_files):

        delay_ms = max(
            0,
            int(item["start"] * 1000)
        )

        filters.append(
            f"[{index}:a]"
            f"adelay={delay_ms}:all=1,"
            f"aresample=44100"
            f"[a{index}]"
        )

    inputs = "".join(
        f"[a{i}]"
        for i in range(len(voice_files))
    )

    filters.append(
        f"{inputs}"
        f"amix="
        f"inputs={len(voice_files)}:"
        f"duration=longest:"
        f"dropout_transition=0"
        f"[out]"
    )

    filter_complex = ";".join(filters)

    command.extend([

        "-filter_complex",
        filter_complex,

        "-map",
        "[out]",

        "-t",
        str(duration),

        "-ac",
        "2",

        "-ar",
        "44100",

        "-c:a",
        "aac",

        "-b:a",
        "128k",

        str(output_audio)
    ])

    run_command(command)


# ============================================================
# CREATE 9:16 VIDEO
# ============================================================

def render_video(
    input_video,
    hindi_audio,
    output_video,
    progress
):

    progress(
        0.75,
        desc="Rendering 9:16 video..."
    )

    video_filter = (
        "scale=1080:1920:"
        "force_original_aspect_ratio=increase,"
        "crop=1080:1920,"
        "setsar=1"
    )

    run_command([

        "ffmpeg",
        "-y",

        "-i",
        str(input_video),

        "-i",
        str(hindi_audio),

        "-map",
        "0:v:0",

        "-map",
        "1:a:0",

        "-vf",
        video_filter,

        "-c:v",
        "libx264",

        "-preset",
        "veryfast",

        "-crf",
        "26",

        "-pix_fmt",
        "yuv420p",

        "-c:a",
        "aac",

        "-b:a",
        "128k",

        "-movflags",
        "+faststart",

        "-shortest",

        str(output_video)
    ])

    progress(
        1.0,
        desc="Completed!"
    )


# ============================================================
# CLEANUP
# ============================================================

def cleanup(path):

    try:

        if path.exists():

            shutil.rmtree(
                path,
                ignore_errors=True
            )

    except Exception as e:

        print(
            "Cleanup error:",
            e
        )


# ============================================================
# MAIN CONVERTER
# ============================================================

def convert_video(
    video_file,
    progress=gr.Progress()
):

    if not video_file:

        raise gr.Error(
            "Please upload a video."
        )

    job_id = uuid.uuid4().hex

    job_dir = (
        BASE_DIR /
        "jobs" /
        job_id
    )

    job_dir.mkdir(
        parents=True,
        exist_ok=True
    )

    input_video = (
        job_dir /
        "input.mp4"
    )

    source_audio = (
        job_dir /
        "source.wav"
    )

    hindi_audio = (
        job_dir /
        "hindi.m4a"
    )

    output_video = (
        OUTPUT_DIR /
        f"hindi_{job_id}.mp4"
    )

    try:

        # ----------------------------------------------------
        # PREPARE
        # ----------------------------------------------------

        progress(
            0.02,
            desc="Preparing video..."
        )

        shutil.copyfile(
            str(video_file),
            str(input_video)
        )

        # ----------------------------------------------------
        # DURATION
        # ----------------------------------------------------

        duration = get_video_duration(
            input_video
        )

        print(
            "Duration:",
            duration
        )

        if duration > 30 * 60:

            raise gr.Error(
                "Maximum video length is 30 minutes."
            )

        # ----------------------------------------------------
        # EXTRACT AUDIO
        # ----------------------------------------------------

        progress(
            0.08,
            desc="Extracting Chinese audio..."
        )

        extract_audio(
            input_video,
            source_audio
        )

        # ----------------------------------------------------
        # TRANSCRIBE
        # ----------------------------------------------------

        progress(
            0.12,
            desc="Recognizing Chinese speech..."
        )

        chinese_segments = transcribe_chinese(
            source_audio,
            progress
        )

        if not chinese_segments:

            raise gr.Error(
                "Chinese speech not detected."
            )

        # ----------------------------------------------------
        # TRANSLATE
        # ----------------------------------------------------

        progress(
            0.30,
            desc="Translating into Hindi..."
        )

        hindi_segments = translate_to_hindi(
            chinese_segments,
            progress
        )

        if not hindi_segments:

            raise gr.Error(
                "Chinese-to-Hindi translation failed. "
                "Please try again later."
            )

        # ----------------------------------------------------
        # HINDI VOICE
        # ----------------------------------------------------

        progress(
            0.45,
            desc="Creating Hindi voice-over..."
        )

        create_hindi_audio(
            hindi_segments,
            duration,
            hindi_audio,
            job_dir,
            progress
        )

        # ----------------------------------------------------
        # FINAL VIDEO
        # ----------------------------------------------------

        render_video(
            input_video,
            hindi_audio,
            output_video,
            progress
        )

        print(
            "DONE:",
            output_video
        )

        return str(output_video)

    except gr.Error:

        raise

    except Exception as e:

        print(
            "ERROR:",
            repr(e)
        )

        raise gr.Error(
            str(e)
        )

    finally:

        cleanup(job_dir)


# ============================================================
# USER INTERFACE
# ============================================================

with gr.Blocks(
    title="Chinese → Hindi Video"
) as app:

    gr.Markdown(
        """
# 🇨🇳 → 🇮🇳 Chinese to Hindi Video Converter

Chinese video upload करें और Hindi voice-over वाला **9:16 MP4** बनाएं।

### Automatic Process

**Chinese Video**
→ Chinese Speech
→ Hindi Translation
→ Hindi Voice
→ 9:16 Video
→ **Hindi MP4**

15–20 मिनट के वीडियो के लिए बनाया गया है।
"""
    )

    with gr.Row():

        with gr.Column():

            video_input = gr.File(
                label="📤 Upload Chinese MP4",
                file_types=[
                    ".mp4",
                    ".mov",
                    ".mkv",
                    ".webm"
                ],
                type="filepath"
            )

            convert_button = gr.Button(
                "🇮🇳 Convert to Hindi",
                variant="primary",
                size="lg"
            )

        with gr.Column():

            output_video = gr.File(
                label="📥 Download Hindi Video",
                file_types=[
                    ".mp4"
                ]
            )

    convert_button.click(
        fn=convert_video,
        inputs=video_input,
        outputs=output_video
    )


# ============================================================
# START SERVER
# ============================================================

if __name__ == "__main__":

    port = int(
        os.environ.get(
            "PORT",
            "7860"
        )
    )

    app.queue(
        max_size=2,
        default_concurrency_limit=1
    )

    app.launch(
        server_name="0.0.0.0",
        server_port=port,
        show_error=True
    )
