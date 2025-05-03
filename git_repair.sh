#!/bin/bash

# Script to repair a corrupted Git repository in place within the current directory.
# WARNING: This script permanently deletes the existing .git directory
# and resets the current branch to match the remote 'main' branch.
# !!! BACK UP ANY UNCOMMITTED LOCAL CHANGES TO TRACKED FILES BEFORE RUNNING !!!

set -e # Exit immediately if a command exits with a non-zero status.

echo "--- Starting Git Repair ---"

# Optional: Add a check to ensure the script is run in the correct directory if needed
# REPO_DIR_NAME="phoenix-vapi"
# if [[ "$(basename "$PWD")" != "$REPO_DIR_NAME" ]]; then
#   echo "Error: Please 'cd' into the '$REPO_DIR_NAME' directory before running this script."
#   exit 1
# fi

echo "Step 1: Removing corrupted .git directory..."
rm -rf .git
echo ".git directory removed."

echo "Step 2: Initializing new empty Git repository..."
git init
echo "New repository initialized."

echo "Step 3: Adding remote origin..."
git remote add origin https://github.com/SoulAuctioneer/phoenix-vapi.git || {
    echo "Remote 'origin' may already exist. Attempting to set URL instead."
    git remote set-url origin https://github.com/SoulAuctioneer/phoenix-vapi.git
}
echo "Remote 'origin' set to https://github.com/SoulAuctioneer/phoenix-vapi.git"

echo "Step 4: Fetching all data from remote 'origin'..."
git fetch origin
echo "Fetch complete."

echo "Step 5: Resetting local repository to match 'origin/main'..."
# --- WARNING: This overwrites local tracked files ---
git reset --hard origin/main
# --- Replace 'main' above if your primary branch has a different name ---
echo "Local repository reset to match origin/main."

echo "Step 6: Verifying status..."
git status

echo "--- Git Repair Script Finished Successfully ---" 