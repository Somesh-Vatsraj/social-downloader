import os
import uuid
import subprocess
import shutil
from pathlib import Path

import gradio as gr
from faster_whisper import WhisperModel
from deep_translator import GoogleTranslator
from gtts import gTTS


# =========================================================
# CONFIG
# =========================================================

BASE_DIR = Path("/tmp/chinese_hindi_tool")
UPLOAD_DIR = BASE_DIR / "uploads"
OUTPUT_DIR = BASE_DIR / "outputs"
AUDIO_DIR = BASE_DIR / "audio"

for folder in [UPLOAD_DIR, OUTPUT_DIR, AUDIO_DIR]:
    folder.mkdir(parents=True, exist_ok=True)

# CPU friendly model
# "tiny" = faster
# "small" = better transcription but slower
WHISPER_MODEL = "small"

print("Loading Whisper model...")
model = WhisperModel(
    WHISPER_MODEL,
    device="cpu",
    compute_type="int8"
)
print("Whisper model loaded.")


# =========================================================
# UTILITY
# =========================================================

def run_command(command):
    result = subprocess.run(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )

    if result.returncode != 0:
        raise RuntimeError(
            "Command failed:\n\n" + result.stderr[-5000:]
        )

    return result


def get_video_duration(video_path):
    result = run_command([
        "ffprobe",
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(video_path)
    ])

    return float(result.stdout.strip())


# =========================================================
# EXTRACT AUDIO
# =========================================================

def extract_audio(video_path, audio_path):
    run_command([
        "ffmpeg",
        "-y",
        "-i", str(video_path),
        "-vn",
        "-ac", "1",
        "-ar", "16000",
        "-c:a", "pcm_s16le",
        str(audio_path)
    ])


# =========================================================
# TRANSCRIBE CHINESE
# =========================================================

def transcribe_chinese(audio_path, progress=None):

    segments, info = model.transcribe(
        str(audio_path),
        language="zh",
        beam_size=5,
        vad_filter=True,
        condition_on_previous_text=True
    )

    results = []

    for segment in segments:

        text = segment.text.strip()

        if not text:
            continue

        results.append({
            "start": float(segment.start),
            "end": float(segment.end),
            "text": text
        })

        if progress:
            progress(
                0.25,
                desc=f"Chinese speech detected: {len(results)} segments"
            )

    return results


# =========================================================
# TRANSLATE CHINESE -> HINDI
# =========================================================

def translate_to_hindi(segments, progress=None):

    translator = GoogleTranslator(
        source="zh-CN",
        target="hi"
    )

    translated = []

    total = len(segments)

    for i, segment in enumerate(segments):

        chinese_text = segment["text"].strip()

        if not chinese_text:
            continue

        try:
            hindi_text = translator.translate(chinese_text)

        except Exception as e:
            print("Translation error:", e)
            hindi_text = chinese_text

        translated.append({
            "start": segment["start"],
            "end": segment["end"],
            "text": hindi_text
        })

        if progress:
            percent = 0.25 + (0.20 * ((i + 1) / max(total, 1)))
            progress(
                percent,
                desc=f"Translating to Hindi: {i + 1}/{total}"
            )

    return translated


# =========================================================
# CREATE HINDI VOICE
# =========================================================

def create_hindi_audio(
    segments,
    output_audio,
    video_duration,
    progress=None
):

    generated_files = []

    for i, segment in enumerate(segments):

        text = segment["text"].strip()

        if not text:
            continue

        filename = AUDIO_DIR / f"{uuid.uuid4().hex}.mp3"

        try:
            # Hindi voice
            tts = gTTS(
                text=text,
                lang="hi",
                slow=False
            )

            tts.save(str(filename))

        except Exception as e:
            print("TTS error:", e)
            continue

        generated_files.append({
            "file": filename,
            "start": segment["start"],
            "end": segment["end"]
        })

        if progress:
            percent = 0.45 + (
                0.30 * ((i + 1) / max(len(segments), 1))
            )

            progress(
                percent,
                desc=f"Creating Hindi voice: {i + 1}/{len(segments)}"
            )

    # -----------------------------------------------------
    # Create silent full-length audio
    # -----------------------------------------------------

    silent_audio = AUDIO_DIR / f"{uuid.uuid4().hex}_silent.wav"

    run_command([
        "ffmpeg",
        "-y",
        "-f", "lavfi",
        "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
        "-t", str(video_duration),
        "-c:a", "pcm_s16le",
        str(silent_audio)
    ])

    # -----------------------------------------------------
    # Create delay + audio for every TTS segment
    # -----------------------------------------------------

    input_args = [
        "ffmpeg",
        "-y",
        "-i", str(silent_audio)
    ]

    filter_parts = []

    for i, item in enumerate(generated_files):

        input_args.extend([
            "-i",
            str(item["file"])
        ])

        delay_ms = max(
            0,
            int(item["start"] * 1000)
        )

        filter_parts.append(
            f"[{i + 1}:a]"
            f"adelay={delay_ms}|{delay_ms},"
            f"aresample=44100"
            f"[a{i}]"
        )

    if not generated_files:
        shutil.copy(
            silent_audio,
            output_audio
        )
        return

    # Mix all voices
    voice_inputs = "".join(
        f"[a{i}]"
        for i in range(len(generated_files))
    )

    filter_complex = ";".join(filter_parts)

    filter_complex += (
        f";{voice_inputs}"
        f"amix=inputs={len(generated_files)}:"
        f"duration=longest:"
        f"dropout_transition=0,"
        f"volume=1.0"
        f"[mixed]"
    )

    input_args.extend([
        "-filter_complex",
        filter_complex,
        "-map",
        "[mixed]",
        "-t",
        str(video_duration),
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        str(output_audio)
    ])

    run_command(input_args)


# =========================================================
# CREATE 9:16 VIDEO
# =========================================================

def create_vertical_video(
    input_video,
    hindi_audio,
    output_video,
    progress=None
):

    if progress:
        progress(
            0.80,
            desc="Creating 9:16 vertical video..."
        )

    # -----------------------------------------------------
    # 9:16 crop
    #
    # scale to height 1920
    # crop width 1080
    # -----------------------------------------------------

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
        "23",

        "-c:a",
        "aac",

        "-b:a",
        "192k",

        "-movflags",
        "+faststart",

        "-shortest",

        str(output_video)
    ])

    if progress:
        progress(
            1.0,
            desc="Finished!"
        )


# =========================================================
# MAIN PROCESS
# =========================================================

def convert_video(video_file, progress=gr.Progress()):

    if video_file is None:
        raise gr.Error("Please upload a video.")

    job_id = uuid.uuid4().hex

    input_path = UPLOAD_DIR / f"{job_id}.mp4"
    source_audio = AUDIO_DIR / f"{job_id}_source.wav"
    hindi_audio = AUDIO_DIR / f"{job_id}_hindi.m4a"
    output_path = OUTPUT_DIR / f"{job_id}_hindi_9x16.mp4"

    try:

        progress(
            0.02,
            desc="Preparing video..."
        )

        # Copy uploaded file
        shutil.copy(
            str(video_file),
            str(input_path)
        )

        # -------------------------------------------------
        # Duration
        # -------------------------------------------------

        duration = get_video_duration(input_path)

        if duration > 45 * 60:
            raise gr.Error(
                "Maximum video length is 45 minutes."
            )

        # -------------------------------------------------
        # Extract original audio
        # -------------------------------------------------

        progress(
            0.08,
            desc="Extracting Chinese audio..."
        )

        extract_audio(
            input_path,
            source_audio
        )

        # -------------------------------------------------
        # Speech recognition
        # -------------------------------------------------

        progress(
            0.15,
            desc="Recognizing Chinese speech..."
        )

        segments = transcribe_chinese(
            source_audio,
            progress
        )

        if not segments:
            raise gr.Error(
                "Chinese speech was not detected."
            )

        # -------------------------------------------------
        # Translation
        # -------------------------------------------------

        progress(
            0.30,
            desc="Translating Chinese to Hindi..."
        )

        hindi_segments = translate_to_hindi(
            segments,
            progress
        )

        # -------------------------------------------------
        # Hindi voice
        # -------------------------------------------------

        progress(
            0.50,
            desc="Generating Hindi voice-over..."
        )

        create_hindi_audio(
            hindi_segments,
            hindi_audio,
            duration,
            progress
        )

        # -------------------------------------------------
        # Final video
        # -------------------------------------------------

        create_vertical_video(
            input_path,
            hindi_audio,
            output_path,
            progress
        )

        return str(output_path)

    except Exception as e:

        print("ERROR:", repr(e))

        raise gr.Error(
            f"Video processing failed:\n{str(e)}"
        )

    finally:

        # Cleanup temporary files
        for file in [
            input_path,
            source_audio,
            hindi_audio
        ]:

            try:
                if file.exists():
                    file.unlink()
            except:
                pass


# =========================================================
# GRADIO UI
# =========================================================

DESCRIPTION = """
# 🇨🇳 ➜ 🇮🇳 Chinese → Hindi Video Converter

Chinese video upload करें और Hindi voice-over वाला **9:16 MP4** प्राप्त करें।

### Features
- Chinese speech recognition
- Chinese → Hindi translation
- Hindi voice-over
- Original audio replace
- 9:16 vertical video
- MP4 output
"""

with gr.Blocks(
    title="Chinese to Hindi Video Converter"
) as demo:

    gr.Markdown(DESCRIPTION)

    with gr.Row():

        with gr.Column():

            video_input = gr.Video(
                label="Upload Chinese Video",
                sources=["upload"],
                type="filepath"
            )

            convert_button = gr.Button(
                "🇮🇳 Convert to Hindi Video",
                variant="primary"
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


# =========================================================
# START SERVER
# =========================================================

if __name__ == "__main__":

    port = int(
        os.environ.get("PORT", 7860)
    )

    demo.queue(
        max_size=5
    ).launch(
        server_name="0.0.0.0",
        server_port=port,
        show_error=True
    )
