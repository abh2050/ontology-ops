"""Assemble genuine browser recordings into the 3:40 project demonstration.

Uses local macOS speech synthesis, labelled as computer-generated narration.
No UI is recreated. Cuts, end-frame holds and compressed drill waiting are
disclosed in the video and its evidence manifest.
"""

import argparse
import json
import subprocess
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
SECTIONS = [
    ("01-queue", 25, "LIVE AWS · Operator · Computer-generated narration",
     "This is Relay, a delivery-exception investigation workspace running on AWS. "
     "The decision is whether to open an internal investigation. The live operator sees "
     "645 late open orders within explicitly granted seller scope. The historical date is "
     "dataset local. Queue urgency is a deterministic prioritization heuristic."),
    ("02-relationships", 45, "LIVE AWS · Typed relationships and authorized evidence",
     "Opening an order connects it to its customer, seller, and related late orders. "
     "The graph is a display projection of authorized evidence. A seller relationship "
     "means fulfilment of an order line; it does not establish fault. Selecting the "
     "seller exposes exact order counts and that seller's own line value. Selecting "
     "an edge explains its business meaning. Authorization is applied before joins, "
     "counts, totals, and graph construction. An order spanning two operators' seller "
     "scopes is invisible to both. The reviewer must independently hold every target's scope."),
    ("03-context", 35, "LIVE AWS · Synthetic scenario explicitly disclosed",
     "The optional scenario adds fictional carrier and disruption context. Every use "
     "is labelled Synthetic scenario. Temporal or regional overlap is context, not proof "
     "of the real cause of delay. The cause remains unknown. The graph shows at most "
     "fifty nodes. Exact authorized totals are computed separately from that display cap. "
     "Historical evidence masks events occurring after the selected as-of date."),
    ("04-proposal", 22, "LIVE AWS · Actual model abstention · Save refused · No case created",
     "This order already has an earlier demo case. A real Bedrock job completes with "
     "validated findings but no proposed action. Saving returns conflict, and no second "
     "case is created. This is the actual recorded outcome, not a simulated model response."),
    ("05-independent-approval", 13, "LIVE AWS · Earlier checked case · Separate reviewer",
     "Separately, the reviewer opens the earlier independently checked demo case. "
     "It is already executed. That approval created one internal case; repeat approval "
     "was refused. It did not approve the no-action attempt."),
    ("06-ungranted-viewer", 15, "LIVE AWS · Viewer · Zero seller grants",
     "The viewer is authenticated but has zero seller grants. The live queue therefore "
     "contains no visible orders and zero exposure. A role never implies access to sellers."),
    ("07-crash-redelivery", 15, "FAULT INJECTION · Capture + recovery readback · Edited wait",
     "The worker crashes before acknowledging SQS. After a recording interruption, live "
     "readback confirms the same ready job and a drained queue. Independent approval "
     "creates one case; repeat approval returns conflict."),
    ("08-measured-evidence", 15, "M5 HISTORICAL RESULTS · Before M6 citation fix",
     "In the historical evaluation, B zero scored one hundred percent; the best candidate, "
     "fifty-eight point one. Read latency was five hundred ninety-one milliseconds at "
     "p ninety-five. Evaluation ran locally with Bedrock and predates the citation fix."),
    ("09-architecture", 10, "ARCHITECTURE · Native AWS service symbols",
     "CloudFront fronts the load balancer and Fargate API. Private PostgreSQL stores "
     "durable state. A separate SQS worker invokes Bedrock."),
    ("10-recommendation", 10, "DECISION · Recommend the deterministic workspace",
     "The candidate did not beat the deterministic workspace. Recommend B zero. Human "
     "investigation speed and financial return remain untested."),
    ("11-static-replay", 15, "STATIC REPLAY · Authored fixtures · All actions simulated",
     "The static replay contains authored fixtures and visibly simulated actions. It "
     "makes zero backend API calls. Live source data is Olist, under Creative Commons "
     "Attribution NonCommercial ShareAlike. This video uses computer-generated narration."),
]


def run(args):
    subprocess.run(args, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


def duration(file):
    return float(subprocess.check_output(["ffprobe", "-v", "error", "-show_entries",
                                         "format=duration", "-of", "default=nw=1:nk=1",
                                         str(file)], text=True).strip())


def overlay_image(file, text, heading=False):
    """Render editorial labels only; never redraw or alter the captured UI."""
    image = Image.new("RGBA", (1600, 900))
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial.ttf",
                             18 if heading else 25)
    if heading:
        draw.rectangle((0, 0, 1600, 38), fill=(16, 39, 57, 245))
        draw.rectangle((0, 780, 1600, 900), fill=(16, 39, 57, 240))
        draw.text((24, 8), text, font=font, fill="white")
    else:
        lines = textwrap.wrap(text, width=112)
        for row, line in enumerate(lines):
            box = draw.textbbox((0, 0), line, font=font)
            draw.text(((1600 - box[2]) / 2, 817 + row * 32), line, font=font, fill="white")
    image.save(file)


def timecode(seconds, ass=False):
    h = int(seconds // 3600)
    m = int(seconds % 3600 // 60)
    s = seconds % 60
    return f"{h}:{m:02}:{s:05.2f}" if ass else f"{h:02}:{m:02}:{s:06.3f}".replace(".", ",")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--capture", type=Path, required=True)
    parser.add_argument("--drill", type=Path)
    parser.add_argument("--audio-only", action="store_true")
    args = parser.parse_args()
    target = args.capture / "finished"
    target.mkdir(exist_ok=True)
    captions, transcript, measures = [], [], []
    cursor = 0
    for name, seconds, heading, narration in SECTIONS:
        text = target / f"{name}.txt"
        unchanged = text.exists() and text.read_text() == narration + "\n"
        text.write_text(narration + "\n")
        audio = target / f"{name}.aiff"
        if not audio.exists() or not unchanged:
            run(["say", "-v", "Samantha", "-r", "155", "-f", str(text), "-o", str(audio)])
        transcript.append(f"{timecode(cursor)} — {heading}\n{narration}\n")
        if args.audio_only:
            print(f"Prepared narration {name}: {duration(audio):.1f}s for {seconds}s scene",
                  flush=True)
            cursor += seconds
            continue
        source = (args.drill if name == "07-crash-redelivery" else args.capture) / f"{name}.webm"
        if name == "07-crash-redelivery":
            combined = args.drill / "07-crash-and-recovery.webm"
            if combined.is_file():
                source = combined
        if not source.is_file():
            raise FileNotFoundError(f"Missing genuine capture: {source.name}")
        length = duration(source)
        voice = duration(audio)
        pace = max(1, voice / (seconds - 0.4))
        subtitle = target / f"{name}.ass"
        sentences = [s.strip() + "." for s in narration.split(".") if s.strip()]
        ass = ["[Script Info]", "ScriptType: v4.00+", "PlayResX: 1600", "PlayResY: 900",
               "[V4+ Styles]", "Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,"
               "OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,"
               "Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding",
               "Style: Default,Arial,25,&H00FFFFFF,&H00FFFFFF,&H00000000,&HAA102739,"
               "0,0,0,0,100,100,0,0,1,1,0,2,60,60,30,1", "[Events]",
               "Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text"]
        sentence_start = 0
        overlays = []
        speech_seconds = min(voice / pace, seconds - 0.4)
        total_words = sum(len(s.split()) for s in sentences)
        for sentence in sentences:
            span = speech_seconds * len(sentence.split()) / total_words
            end = sentence_start + span
            wrapped = r"\N".join(textwrap.wrap(sentence, width=112))
            ass.append(f"Dialogue: 0,{timecode(sentence_start, True)},"
                       f"{timecode(end, True)},Default,,0,0,0,,{wrapped}")
            captions.append((cursor + sentence_start, cursor + end, sentence))
            png = target / f"{name}-caption-{len(overlays)}.png"
            overlay_image(png, sentence)
            overlays.append((png, sentence_start, end))
            sentence_start = end
        subtitle.write_text("\n".join(ass) + "\n")
        label = target / f"{name}-heading.txt"
        label.write_text(heading + "\n")
        header = target / f"{name}-header.png"
        overlay_image(header, heading, heading=True)
        common = ("scale=1600:900:force_original_aspect_ratio=decrease,"
                  "pad=1600:900:(ow-iw)/2:(oh-ih)/2:color=0x102739,setsar=1,fps=30,")
        if name == "07-crash-redelivery" and length > 30:
            middle_end = length - 7
            first_start = 25 if source.name == "07-crash-and-recovery.webm" else 1
            first_end = first_start + 4
            chain = (f"[0:v]split=3[a][b][c];[a]trim=start={first_start}:end={first_end},"
                     "setpts=PTS-STARTPTS[x];"
                     f"[b]trim=start={first_end}:end={middle_end},"
                     f"setpts=(PTS-STARTPTS)*6/{middle_end-first_end}[y];"
                     f"[c]trim=start={length-6}:end={length-1},setpts=PTS-STARTPTS[z];"
                     "[x][y][z]concat=n=3:v=1:a=0[edited];[edited]")
        else:
            start = min(1.5, length / 10)
            rate = min(1, seconds / max(1, length - start))
            chain = f"[0:v]trim=start={start},setpts=(PTS-STARTPTS)*{rate},"
        chain += common + ("tpad=stop_mode=clone:stop_duration=3,"
                           f"trim=duration={seconds}[base];[base][2:v]overlay=0:0[h]")
        previous = "h"
        for index, (_, start, end) in enumerate(overlays):
            current = f"c{index}"
            chain += (f";[{previous}][{index+3}:v]overlay=0:0:"
                      f"enable='between(t,{start},{end})'[{current}]")
            previous = current
        chain += f";[{previous}]null[v];[1:a]atempo={pace},apad,atrim=0:{seconds}[a]"
        encoded = target / f"{name}.mp4"
        image_inputs = []
        for png in [header, *(png for png, _, _ in overlays)]:
            image_inputs.extend(["-loop", "1", "-framerate", "30", "-i", str(png)])
        run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(source),
             "-i", str(audio), *image_inputs, "-filter_complex", chain,
             "-map", "[v]", "-map", "[a]",
             "-c:v", "libx264", "-preset", "fast", "-crf", "19", "-pix_fmt", "yuv420p",
             "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-t", str(seconds), str(encoded)])
        measures.append({"scene": name, "source_seconds": length, "edited_seconds": seconds,
                         "narration_seconds": voice, "narration_pace": pace})
        cursor += seconds
        print(f"Assembled {name}: {seconds}s", flush=True)
    (target / "narration.txt").write_text("\n".join(transcript))
    if args.audio_only:
        return
    concat = target / "clips.txt"
    concat.write_text("\n".join(f"file '{target / (name + '.mp4')}'"
                                for name, *_ in SECTIONS) + "\n")
    video = target / "ontology-operational-ai-demo.mp4"
    run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "concat", "-safe", "0",
         "-i", str(concat), "-c", "copy", "-t", "220", "-movflags", "+faststart", str(video)])
    srt = [f"{i}\n{timecode(a)} --> {timecode(b)}\n{text}\n"
           for i, (a, b, text) in enumerate(captions, 1)]
    (target / "captions.srt").write_text("\n".join(srt))
    report = {"video": str(video.relative_to(ROOT)), "duration_seconds": duration(video),
              "resolution": "1600x900", "narration": "Computer-generated local macOS voice",
              "editing": "Genuine live UI footage; cuts, shortened waits and end-frame holds. "
              "Fault-injection footage includes an interrupted capture and later readback "
              "of the same job; the interval is edited and compressed. "
              "Architecture is a repository artifact; static replay labelled separately.",
              "scenes": measures}
    (target / "render-report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(f"Completed {video}; measured duration {report['duration_seconds']:.3f}s")


if __name__ == "__main__":
    main()
