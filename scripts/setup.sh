#!/bin/bash
set -e

# Step 1: Syncing dependencies
echo "Syncing dependencies..."
uv sync

# Step 2: Install pre-commit hooks
echo "Installing pre-commit hooks..."
if [ -f ".git/hooks/pre-commit" ]; then
    echo "Pre-commit already installed."
else
    uv run pre-commit install
fi

# Step 3: Run validation
echo "Running validation..."
uv run pre-commit run --all-files

echo "Setup completed successfully."
