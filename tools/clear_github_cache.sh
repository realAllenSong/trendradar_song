#!/bin/bash
# Clear GitHub Actions cache to force re-download of full precision models

set -e

echo "=== Clearing GitHub Actions Cache for VoxCPM Models ==="
echo ""
echo "This will clear the old quantized models cache and force download of full precision models."
echo ""

# Get repository info
REPO="realAllenSong/trendradar_song"
echo "Repository: $REPO"

# Check if gh CLI is installed
if ! command -v gh &> /dev/null; then
    echo "Error: GitHub CLI (gh) is not installed"
    echo "Install it: brew install gh"
    echo "Or visit: https://cli.github.com/"
    exit 1
fi

# Check if authenticated
if ! gh auth status &> /dev/null; then
    echo "Error: Not authenticated with GitHub"
    echo "Run: gh auth login"
    exit 1
fi

echo ""
echo "Listing current caches..."
gh cache list --repo "$REPO" || true

echo ""
echo "Deleting VoxCPM model caches..."

# Delete all caches matching voxcpm-models
gh cache delete --repo "$REPO" --all -c 'voxcpm-models*' 2>/dev/null || echo "No voxcpm-models cache found"

# Delete all caches matching hf-cache
gh cache delete --repo "$REPO" --all -c 'hf-cache*' 2>/dev/null || echo "No hf-cache found"

echo ""
echo "✅ Cache cleared successfully!"
echo ""
echo "Next steps:"
echo "1. Commit the updated ensure_voxcpm_assets.py"
echo "2. Push to GitHub"
echo "3. Trigger GitHub Actions workflow"
echo "4. The workflow will download full precision models from HuggingFace"
