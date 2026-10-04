import os
import uuid
import shutil
import subprocess
from pathlib import Path

import gradio as gr
from faster_whisper import WhisperModel
from deep_translator import GoogleTranslator
from gtts import gTTS


# ============================================================
# CONFIG
# ============================================================

BASE_DIR = Path("/tmp/chinese_hindi")

UPLOAD_DIR = BASE_DIR / "uploads"
AUDIO_DIR = BASE_DIR / "audio"
OUTPUT_DIR = BASE_DIR / "outputs"

for folder in [UPLOAD_DIR, AUDIO_DIR, OUTPUT_DIR]:
    folder.mkdir(parents=True, exist_ok=True)


# IMPORTANT:
# tiny model is used because Render Free/low-RAM
# instances can run out of memory with "small".
WHISPER_MODEL_NAME = "tiny"

whisper_model = None


# ============================================================
# WHISPER - LAZY LOAD
# ============================================================

def get_whisper_model():

    global whisper_model

    if whisper_model is None:

        print("========================================")
        print("Loading Whisper tiny model...")
        print("========================================")

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
# COMMAND RUNNER
# ============================================================

def run_command(command):

    print("Running:", " ".join(map(str, command)))

    result = subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )

    if result.returncode != 0:

        print(result.stderr)

        raise RuntimeError(
            result.stderr[-4000:]
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
# CHINESE SPEECH TO TEXT
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

    result = []

    count = 0

    for segment in segments:

        text = segment.text.strip()

        if not text:
            continue

        result.append({

            "start": float(segment.start),

            "end": float(segment.end),

            "text": text
        })

        count += 1

        progress(
            0.15,
            desc=f"Chinese speech detected: {count}"
        )

    print(
        "Transcription segments:",
        len(result)
    )

    return result


# ============================================================
# CHINESE -> HINDI
# ============================================================

def translate_chinese_to_hindi(
    segments,
    progress
):

    translator = GoogleTranslator(
        source="zh-CN",
        target="hi"
    )

    result = []

    total = len(segments)

    print("Starting translation...")

    for index, segment in enumerate(segments):

        chinese = segment["text"].strip()

        if not chinese:
            continue

        hindi = ""

        try:

            hindi = translator.translate(
                chinese
            )

        except Exception as e:

            print(
                "Translation error:",
                e
            )

            # If translation fails, skip this segment.
            continue

        if hindi:

            result.append({

                "start": segment["start"],

                "end": segment["end"],

                "text": hindi.strip()
            })

        percent = 0.25 + (
            0.20 *
            ((index + 1) / max(total, 1))
        )

        progress(
            percent,
            desc=f"Translating: {index + 1}/{total}"
        )

    print(
        "Translated segments:",
        len(result)
    )

    return result


# ============================================================
# CREATE ONE TTS FILE
# ============================================================

def create_tts(text, filename):

    tts = gTTS(
        text=text,
        lang="hi",
        slow=False
    )

    tts.save(str(filename))


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
            "No Hindi text was generated."
        )

    generated = []

    total = len(segments)

    print("Generating Hindi voice...")

    for index, segment in enumerate(segments):

        text = segment["text"].strip()

        if not text:
            continue

        tts_file = (
            job_dir /
            f"voice_{index:05d}.mp3"
        )

        try:

            create_tts(
                text,
                tts_file
            )

            generated.append({

                "file": tts_file,

                "start": segment["start"]
            })

        except Exception as e:

            print(
                "TTS failed:",
                e
            )

        percent = 0.45 + (
            0.25 *
            ((index + 1) / max(total, 1))
        )

        progress(
            percent,
            desc=f"Creating Hindi voice: {index + 1}/{total}"
        )

    if not generated:

        raise RuntimeError(
            "Hindi voice could not be generated."
        )

    # --------------------------------------------------------
    # Build ffmpeg command
    # --------------------------------------------------------

    command = [
        "ffmpeg",
        "-y"
    ]

    # Add every generated voice file
    for item in generated:

        command.extend([
            "-i",
            str(item["file"])
        ])

    filter_parts = []

    for index, item in enumerate(generated):

        delay = max(
            0,
            int(item["start"] * 1000)
        )

        filter_parts.append(
            f"[{index}:a]"
            f"adelay={delay}:all=1,"
            f"aresample=44100"
            f"[a{index}]"
        )

    inputs = "".join(
        f"[a{i}]"
        for i in range(len(generated))
    )

    filter_parts.append(
        f"{inputs}"
        f"amix="
        f"inputs={len(generated)}:"
        f"duration=longest:"
        f"dropout_transition=0,"
        f"loudnorm=I=-16:TP=-1.5:LRA=11"
        f"[out]"
    )

    filter_complex = ";".join(
        filter_parts
    )

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

    print(
        "Hindi audio created:",
        output_audio
    )


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

    # Center crop.
    #
    # This converts the source into 1080x1920.
    #
    # If the original video is landscape,
    # the sides will be cropped.

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

        # Video from original
        "-map",
        "0:v:0",

        # Hindi audio
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

def cleanup_directory(directory):

    try:

        if directory.exists():

            shutil.rmtree(
                directory,
                ignore_errors=True
            )

    except Exception as e:

        print(
            "Cleanup error:",
            e
        )


# ============================================================
# MAIN
# ============================================================

def convert_video(
    video_file,
    progress=gr.Progress()
):

    if not video_file:

        raise gr.Error(
            "Please upload a Chinese video."
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
        f"hindivideo_{job_id}.mp4"
    )

    try:

        # ----------------------------------------------------
        # COPY INPUT
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
            "Video duration:",
            duration,
            "seconds"
        )

        # Maximum 30 minutes
        if duration > 30 * 60:

            raise gr.Error(
                "Maximum supported video length is 30 minutes."
            )

        # ----------------------------------------------------
        # AUDIO
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
        # TRANSCRIPTION
        # ----------------------------------------------------

        progress(
            0.12,
            desc="Recognizing Chinese speech..."
        )

        chinese_segments = (
            transcribe_chinese(
                source_audio,
                progress
            )
        )

        if not chinese_segments:

            raise gr.Error(
                "Chinese speech was not detected."
            )

        # ----------------------------------------------------
        # TRANSLATION
        # ----------------------------------------------------

        progress(
            0.30,
            desc="Translating Chinese to Hindi..."
        )

        hindi_segments = (
            translate_chinese_to_hindi(
                chinese_segments,
                progress
            )
        )

        if not hindi_segments:

            raise gr.Error(
                "Chinese text could not be translated."
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
        # RENDER
        # ----------------------------------------------------

        render_video(
            input_video,
            hindi_audio,
            output_video,
            progress
        )

        print(
            "FINAL VIDEO:",
            output_video
        )

        return str(output_video)

    except gr.Error:
        raise

    except Exception as e:

        print(
            "PROCESSING ERROR:",
            repr(e)
        )

        raise gr.Error(
            "Processing failed: "
            + str(e)
        )

    finally:

        # Delete large temporary files
        cleanup_directory(
            job_dir
        )


# ============================================================
# UI
# ============================================================

DESCRIPTION = """
# 🇨🇳 → 🇮🇳 Chinese to Hindi Video Converter

Chinese video upload करें और Hindi voice-over वाला **9:16 MP4** बनाएं।

### क्या होगा?

1. Chinese speech detect होगी
2. Chinese → Hindi translation होगी
3. Hindi voice-over बनेगा
4. Original audio की जगह Hindi audio लगेगा
5. Video 9:16 में render होगा

**Recommended:** 15–20 minute videos
"""

with gr.Blocks(
    title="Chinese → Hindi Video Converter"
) as app:

    gr.Markdown(
        DESCRIPTION
    )

    with gr.Row():

        with gr.Column():

            video_input = gr.Video(
                label="Chinese Video Upload",
                sources=["upload"],
                type="filepath"
            )

            convert_button = gr.Button(
                "🇮🇳 Convert to Hindi",
                variant="primary",
                size="lg"
            )

        with gr.Column():

            output_video = gr.Video(
                label="Hindi 9:16 Video",
                autoplay=False
            )

    convert_button.click(
        fn=convert_video,
        inputs=video_input,
        outputs=output_video
    )


# ============================================================
# SERVER
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
