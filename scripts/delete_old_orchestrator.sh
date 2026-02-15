#!/bin/bash
# Remove the old monolithic orchestrator.py after verifying the package replacement works.
# Run tests first: pytest tests/ -k orchestrator
set -e

OLD_FILE="koda2/orchestrator.py"

if [ -f "$OLD_FILE" ]; then
    echo "Backing up $OLD_FILE to $OLD_FILE.bak"
    cp "$OLD_FILE" "$OLD_FILE.bak"
    echo "Removing $OLD_FILE"
    rm "$OLD_FILE"
    echo "Done. Run tests to verify: pytest tests/ -k orchestrator"
    echo "If tests fail, restore with: mv $OLD_FILE.bak $OLD_FILE"
else
    echo "$OLD_FILE not found — already removed or package is in use."
fi
