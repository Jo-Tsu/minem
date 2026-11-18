#!/bin/bash
# Install the Finder shortcut for the current project location.
set -euo pipefail

project=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd -P)
desktop=$(/usr/bin/osascript -e 'POSIX path of (path to desktop folder)')
target="${desktop%/}/MineM.app"
identifier=com.minem.web-launcher
if [[ -e "$target" || -L "$target" ]]; then
    current=$(/usr/libexec/PlistBuddy -c 'Print :CFBundleIdentifier' "$target/Contents/Info.plist" 2>/dev/null || true)
    if [[ "$current" != "$identifier" || -L "$target" ]]; then
        printf '桌面已有同名项目：%s\n' "$target" >&2
        exit 1
    fi
fi

mkdir -p "$project/runtime"
work=$(mktemp -d "$project/runtime/.launcher.XXXXXX")
trap 'rm -rf -- "$work"' EXIT
app="$work/MineM.app"

mkdir -p "$app/Contents/MacOS" "$app/Contents/Resources"
/usr/bin/xcrun swiftc -O "$project/scripts/MineMLauncher.swift" -o "$app/Contents/MacOS/MineM"
plist="$app/Contents/Info.plist"
/usr/bin/plutil -create xml1 "$plist"
/usr/bin/plutil -insert CFBundleIdentifier -string "$identifier" "$plist"
/usr/bin/plutil -insert CFBundleExecutable -string MineM "$plist"
/usr/bin/plutil -insert CFBundleName -string MineM "$plist"
/usr/bin/plutil -insert CFBundleVersion -string "$(date '+%Y%m%d%H%M%S')" "$plist"
/usr/bin/plutil -insert CFBundlePackageType -string APPL "$plist"
/usr/bin/plutil -insert MineMLaunchScript -string "$project/scripts/start_web.sh" "$plist"
/usr/bin/plutil -insert LSUIElement -bool YES "$plist"

icon="$project/desktop/src-tauri/icons/icon.png"
if [[ -f "$icon" ]]; then
    iconset="$work/MineM.iconset"
    mkdir "$iconset"
    for size in 16 32 128 256 512; do
        /usr/bin/sips -z "$size" "$size" "$icon" --out "$iconset/icon_${size}x${size}.png" >/dev/null
        doubled=$((size * 2))
        /usr/bin/sips -z "$doubled" "$doubled" "$icon" --out "$iconset/icon_${size}x${size}@2x.png" >/dev/null
    done
    /usr/bin/iconutil -c icns "$iconset" -o "$app/Contents/Resources/MineM.icns"
    /usr/bin/plutil -insert CFBundleIconFile -string MineM.icns "$plist"
fi
/usr/bin/codesign --force --sign - "$app"
# Replacing a bundle with ditto alone merges obsolete AppleScript resources.
# Keep the old entry until the newly signed bundle is ready, then replace it.
if [[ -e "$target" ]]; then
    /bin/mv "$target" "$work/PreviousMineM.app"
fi
if ! /bin/mv "$app" "$target"; then
    [[ ! -e "$work/PreviousMineM.app" ]] || /bin/mv "$work/PreviousMineM.app" "$target"
    exit 1
fi
/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister -f "$target"
printf '已安装 %s\n' "$target"
