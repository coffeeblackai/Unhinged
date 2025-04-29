#!/bin/bash
set -e

# Check if tag is provided
if [ -z "$1" ]; then
  echo "Error: Please provide a tag name"
  echo "Usage: ./scripts/release.sh v1.0.0"
  exit 1
fi

TAG=$1
echo "Building and releasing version $TAG"

# Build for all platforms
echo "Building for macOS..."
npm run build:mac

echo "Building for Windows..."
npm run build:win

echo "Building for Linux..."
npm run build:linux

# Check if gh CLI is installed
if ! command -v gh &> /dev/null; then
  echo "GitHub CLI (gh) is not installed. Please install it first:"
  echo "https://cli.github.com/manual/installation"
  exit 1
fi

# Create a new GitHub release
echo "Creating GitHub release for tag $TAG..."
gh release create $TAG \
  --title "Unhinged $TAG" \
  --notes "Release $TAG" \
  --draft

# Upload the artifacts
echo "Uploading macOS artifacts..."
gh release upload $TAG ./dist/*.dmg

echo "Uploading Windows artifacts..."
gh release upload $TAG ./dist/*.exe

echo "Uploading Linux artifacts..."
gh release upload $TAG ./dist/*.AppImage

echo "✅ Release $TAG created and artifacts uploaded!"
echo "The release is currently in draft mode. Go to GitHub to publish it." 