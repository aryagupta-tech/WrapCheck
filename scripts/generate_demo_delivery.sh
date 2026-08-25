#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "$0")/.." && pwd)"
source_frame="$project_root/fixtures/demo_delivery/source/station-office.png"
asset_dir="$project_root/backend/app/demo_assets"
package_dir="$project_root/backend/app/demo_packages"
data_dir="$project_root/backend/app/demo_data"
work_dir="$(mktemp -d)"
trap 'rm -rf "$work_dir"' EXIT

ffmpeg_bin="${FFMPEG_BIN:-/opt/homebrew/bin/ffmpeg}"
ffprobe_bin="${FFPROBE_BIN:-/opt/homebrew/bin/ffprobe}"
python_bin="${PYTHON_BIN:-/Users/arya/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3}"

if [[ ! -f "$source_frame" ]]; then
  echo "Missing generated source frame: $source_frame" >&2
  exit 1
fi

mkdir -p "$asset_dir" "$package_dir"
rm -f "$package_dir/problem-delivery.zip" "$package_dir/recovered-delivery.zip"

make_take() {
  local clip="$1"
  local take="$2"
  local line="$3"
  local pan_x="$4"
  local source_audio="$work_dir/${clip}.aiff"
  local production_audio="$asset_dir/SR12_024B_T${take}.wav"
  local camera_video="$asset_dir/A017_C00${clip}_0825Q7.mp4"
  local overlay="$work_dir/overlay-${clip}.png"

  /usr/bin/say -v Daniel -r 150 "$line" -o "$source_audio"
  "$ffmpeg_bin" -hide_banner -loglevel error -y \
    -i "$source_audio" \
    -f lavfi -i "anoisesrc=color=brown:amplitude=0.006:sample_rate=48000" \
    -filter_complex "[0:a]aresample=48000,adelay=1500|1500,apad=pad_dur=7.2[voice];[1:a]atrim=duration=7.2[room];[voice][room]amix=inputs=2:duration=longest:weights='1 0.35',alimiter=limit=0.92" \
    -t 7.2 -ar 48000 -ac 2 -c:a pcm_s24le "$production_audio"

  "$python_bin" "$project_root/scripts/render_demo_overlay.py" "$overlay" "$clip" "$take"

  "$ffmpeg_bin" -hide_banner -loglevel error -y \
    -loop 1 -framerate 24 -i "$source_frame" -loop 1 -framerate 24 -i "$overlay" -i "$production_audio" \
    -filter_complex "[0:v]scale=1320:743,crop=1280:720:x=${pan_x}:y=11,noise=alls=2.2:allf=t[base];[base][1:v]overlay=0:0,fade=t=in:st=0:d=0.25,fade=t=out:st=6.85:d=0.35[v];[2:a]volume=0.23,lowpass=f=3600,highpass=f=160[a]" \
    -map "[v]" -map "[a]" -t 7.2 -r 24 -c:v libx264 -preset medium -crf 21 \
    -pix_fmt yuv420p -c:a aac -b:a 96k -movflags +faststart "$camera_video"

  "$ffprobe_bin" -v error -show_entries format=duration -of default=nw=1:nk=1 "$camera_video" >/dev/null
  "$ffprobe_bin" -v error -show_entries stream=sample_rate -select_streams a:0 -of default=nw=1:nk=1 "$production_audio" >/dev/null
}

make_take 1 05 "The last train leaves at six. We still have time." 8
make_take 2 06 "The last train leaves at six. We should go now." 20
make_take 3 07 "The last train leaves at six." 32

cat > "$data_dir/camera_report.csv" <<'CSV'
production,shoot_day,camera_roll,card_id,scene,take,circled,video_filename,frame_rate,notes
The Last Signal,Day 12,A017,A017,24B,5,false,A017_C001_0825Q7.mp4,24,Wide master
The Last Signal,Day 12,A017,A017,24B,6,false,A017_C002_0825Q7.mp4,24,Performance alternate
The Last Signal,Day 12,A017,A017,24B,7,true,A017_C003_0825Q7.mp4,24,Circled print
CSV

cat > "$data_dir/sound_report.csv" <<'CSV'
sound_roll,scene,take,audio_filename,channels,notes
SR12,24B,5,SR12_024B_T05.wav,1-2,Boom and lav
SR12,24B,6,SR12_024B_T06.wav,1-2,Boom and lav
SR12,24B,7,SR12_024B_T07.wav,1-2,Circled take clean sound
CSV

cat > "$data_dir/script_notes.csv" <<'CSV'
scene,take,status,editor_note
24B,5,print,Good master; hold for performance
24B,6,alternate,Usable alternate
24B,7,circled,Circled performance; preferred for edit
CSV

file_size() { stat -f %z "$1"; }
file_hash() { shasum -a 256 "$1" | awk '{print $1}'; }

write_manifest_row() {
  local file="$1"
  local kind="$2"
  local roll="$3"
  local card="$4"
  local take="$5"
  local destination="$6"
  local verified="$7"
  local path="$asset_dir/$file"
  local checksum=""
  if [[ "$verified" == "true" ]]; then checksum="$(file_hash "$path")"; fi
  printf '%s,%s,%s,%s,24B,%s,%s,%s,sha256,%s,%s\n' \
    "$file" "$kind" "$roll" "$card" "$take" "$(file_size "$path")" "$destination" "$checksum" "$verified"
}

write_manifest() {
  local variant="$1"
  local target="$data_dir/manifest_${variant}.csv"
  printf 'filename,kind,roll,card_id,scene,take,size_bytes,destination,checksum_algorithm,checksum,verified\n' > "$target"
  for clip in 1 2 3; do
    local take=$((clip + 4))
    local file="A017_C00${clip}_0825Q7.mp4"
    write_manifest_row "$file" video A017 A017 "$take" PRIMARY true >> "$target"
    if [[ "$variant" == "clean" ]]; then
      write_manifest_row "$file" video A017 A017 "$take" SECONDARY true >> "$target"
    else
      write_manifest_row "$file" video A017 A017 "$take" SECONDARY false >> "$target"
    fi
  done
  for take in 05 06 07; do
    if [[ "$variant" == "problem" && "$take" == "07" ]]; then continue; fi
    local file="SR12_024B_T${take}.wav"
    local numeric_take=$((10#$take))
    write_manifest_row "$file" audio SR12 SOUND "$numeric_take" PRIMARY true >> "$target"
    write_manifest_row "$file" audio SR12 SOUND "$numeric_take" SECONDARY true >> "$target"
  done
}

write_manifest problem
write_manifest clean

make_package() {
  local variant="$1"
  local output_variant="$variant"
  if [[ "$variant" == "clean" ]]; then output_variant="recovered"; fi
  local package_work="$work_dir/${output_variant}-delivery"
  mkdir -p "$package_work/reports" "$package_work/media/camera" "$package_work/media/sound"
  cp "$data_dir/camera_report.csv" "$data_dir/sound_report.csv" "$data_dir/script_notes.csv" "$package_work/reports/"
  cp "$data_dir/manifest_${variant}.csv" "$package_work/reports/offload_manifest.csv"
  cp "$asset_dir"/A017_C00*_0825Q7.mp4 "$package_work/media/camera/"
  cp "$asset_dir"/SR12_024B_T05.wav "$asset_dir"/SR12_024B_T06.wav "$package_work/media/sound/"
  if [[ "$variant" == "clean" ]]; then cp "$asset_dir"/SR12_024B_T07.wav "$package_work/media/sound/"; fi
  (
    cd "$work_dir"
    /usr/bin/zip -q -r "$package_dir/${output_variant}-delivery.zip" "${output_variant}-delivery"
  )
}

make_package problem
make_package clean

echo "Created camera takes in $asset_dir"
echo "Created $package_dir/problem-delivery.zip"
echo "Created $package_dir/recovered-delivery.zip"
