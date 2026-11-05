#!/data/data/com.termux/files/usr/bin/bash

set -e

cd "$(dirname "$0")"

echo "🚀 QR Studio GitHub Uploader"
echo "----------------------------"

# Check GitHub login
gh auth status >/dev/null

# Verify repository
EXPECTED="https://github.com/justfortestingnothibghere/QR-Studio.git"
REMOTE=$(git remote get-url origin)

if [ "$REMOTE" != "$EXPECTED" ]; then
    echo "❌ Wrong GitHub repository!"
    exit 1
fi

# Set branch
git branch -M main

# Configure Git identity if missing
if [ -z "$(git config user.name)" ] || [ -z "$(git config user.email)" ]; then
    GH_USER=$(gh api user --jq '.login')
    GH_ID=$(gh api user --jq '.id')

    git config user.name "$GH_USER"
    git config user.email "${GH_ID}+${GH_USER}@users.noreply.github.com"
fi

# Add project files
git add -A

# Security check
FILES=$(git diff --cached --name-only)

if echo "$FILES" | grep -Ei '(^|/)(\.env[^/]*|credentials\.json|secrets\.json|id_rsa|id_ed25519)$|(\.pem|\.key)$'; then
    echo "❌ Possible secret file detected!"
    echo "Upload cancelled. Review staged files."
    git reset
    exit 1
fi

# Check changes
if git diff --cached --quiet; then
    echo "✅ Everything is already up to date!"
    exit 0
fi

echo "📦 Creating commit..."

git commit -m "Update QR Studio"

echo "☁️ Uploading to GitHub..."

git push -u origin main

echo "----------------------------"
echo "✅ QR STUDIO UPLOADED SUCCESSFULLY!"
