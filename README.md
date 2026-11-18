# Transcode

Converts videos into files that play or edit without trouble. Open a terminal in a folder,
run `transcode`, pick the videos and a preset. Results are written next to the originals,
which are never changed.

| Preset | Output | Use it for |
|---|---|---|
| Phone / sharing | `<name> (phone).mp4`: H.264 + AAC, CRF 18, max 1080p | Phones, Google Drive, messengers. Fixes laggy AV1 / high-bitrate exports and FLAC audio. 4K is scaled to 1080p (vertical videos stay vertical). |
| DaVinci Resolve | `<name> (resolve).mov`: DNxHR + PCM | Editing in the free DaVinci Resolve on Linux, which can't open H.264, H.265 or AAC. 10-bit sources stay 10-bit (HQX). |

- Lists each video with codec, resolution, frame rate, audio and length
- Pick one (`2`), several (`1,3`), a range (`2-5`) or all (`a`)
- Progress bar with ETA; Ctrl+C removes the unfinished file
- Skips videos that already have an output for the chosen preset; never lists its own outputs as sources
- Keeps the original file date

## Install

```bash
git clone https://github.com/Krabisko/transcode.git
cd transcode
./install.sh
```

Links `transcode` into `~/.local/bin`. Needs Python 3.8+ and `ffmpeg`.
The Resolve preset uses the NVIDIA GPU to decode when `nvidia-smi` is present.

## Usage

```bash
transcode                    # pick from videos in the current folder
transcode ~/Videos/trip      # pick from another folder
transcode "Timeline 1.mp4"   # convert these files directly
transcode -p phone           # skip the preset question
```

## Resolve export settings that need no transcoding

For a phone-friendly export straight from Resolve: Format MP4, Codec **H.264** (NVIDIA),
Quality **Restrict to** ~15000 kb/s, Audio codec **AAC**. AV1 at "Best" quality makes
~100 Mbit/s files that most phones can't play smoothly.
