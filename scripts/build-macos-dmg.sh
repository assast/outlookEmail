#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "错误：macOS DMG 只能在 macOS 上构建。"
  exit 1
fi

if ! command -v hdiutil >/dev/null 2>&1; then
  echo "错误：未找到 hdiutil。请在 macOS 环境中运行。"
  exit 1
fi

PYTHON_BIN="${PYTHON_BIN:-python3}"
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "错误：未找到 Python：$PYTHON_BIN"
  exit 1
fi

if ! "$PYTHON_BIN" -m PyInstaller --version >/dev/null 2>&1; then
  echo "错误：未安装 PyInstaller。请先运行：$PYTHON_BIN -m pip install -r requirements.txt pyinstaller"
  exit 1
fi

normalize_arch() {
  case "$1" in
    x86_64|amd64|x64) echo "x64" ;;
    arm64|aarch64) echo "arm64" ;;
    *) echo "$1" ;;
  esac
}

VERSION="$(tr -d '[:space:]' < VERSION)"
if [[ -z "$VERSION" ]]; then
  echo "错误：VERSION 文件为空。"
  exit 1
fi

ARCH="$(normalize_arch "${OUTLOOK_EMAIL_MACOS_ARCH:-$(uname -m)}")"
DMG_NAME="${OUTLOOK_EMAIL_DMG_NAME:-OutlookEmail-macos-$ARCH-$VERSION.dmg}"
APP_PATH="$PROJECT_ROOT/dist/OutlookEmail.app"
WORK_DIR="$PROJECT_ROOT/build/macos-dmg"
STAGING_DIR="$WORK_DIR/staging"
DMG_PATH="$PROJECT_ROOT/dist/$DMG_NAME"

"$PYTHON_BIN" -m PyInstaller --noconfirm --clean outlookEmail.spec

if [[ ! -d "$APP_PATH" ]]; then
  echo "错误：未生成 $APP_PATH"
  exit 1
fi

rm -rf "$STAGING_DIR"
rm -f "$DMG_PATH"
mkdir -p "$STAGING_DIR" "$PROJECT_ROOT/dist"

ditto "$APP_PATH" "$STAGING_DIR/OutlookEmail.app"
ln -s /Applications "$STAGING_DIR/Applications"

hdiutil create \
  -volname "OutlookEmail" \
  -srcfolder "$STAGING_DIR" \
  -ov \
  -format UDZO \
  "$DMG_PATH"

echo "macOS 安装包已生成：$DMG_PATH"
