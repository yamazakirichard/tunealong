#!/usr/bin/env bash
# Generate the test media in fixtures/originals/. Output is gitignored.
#   AAAAAAAAAAA.webm  "tone440": VP9 + Opus, 440 Hz sine
#   BBBBBBBBBBB.webm  VP9 + Opus, 330 Hz sine
#   CCCCCCCCCCC.mp4   H.264 + AAC, 440 Hz sine (backend tests only)
# All are 10 s, 320x240 colour bars with the frame number burned in.
set -euo pipefail

out="$(cd "$(dirname "$0")/.." && pwd)/fixtures/originals"
mkdir -p "$out"

video="smptebars=size=320x240:rate=25:duration=10,drawtext=text='%{frame_num}':x=10:y=10:fontsize=32:fontcolor=white:box=1:boxcolor=black"

gen() {  # gen <freq> <dest> <codec args...>
  local freq=$1 dest=$2; shift 2
  [[ -s "$dest" ]] && { echo "exists: $dest"; return; }
  ffmpeg -nostdin -hide_banner -loglevel error -y \
    -f lavfi -i "$video" \
    -f lavfi -i "sine=frequency=${freq}:sample_rate=48000:duration=10" \
    -ac 2 -shortest "$@" "$dest.tmp.${dest##*.}"
  mv "$dest.tmp.${dest##*.}" "$dest"
  echo "wrote: $dest"
}

vp9=(-c:v libvpx-vp9 -b:v 200k -deadline realtime -cpu-used 8 -c:a libopus -b:a 96k)
h264=(-c:v libx264 -preset veryfast -pix_fmt yuv420p -c:a aac -b:a 128k -movflags +faststart)

gen 440 "$out/AAAAAAAAAAA.webm" "${vp9[@]}"
gen 330 "$out/BBBBBBBBBBB.webm" "${vp9[@]}"
gen 440 "$out/CCCCCCCCCCC.mp4"  "${h264[@]}"
