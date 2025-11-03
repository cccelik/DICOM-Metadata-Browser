#!/bin/bash

# Script to keep only one file per folder in a directory tree.
# WARNING: This script will permanently delete files. Use with caution!
# It keeps the first file found (alphabetically by default).

# --- Configuration ---
# Set the root directory you want to process.
# IMPORTANT: Change '/path/to/your/root/folder' to your actual folder.
ROOT_DIR="/mnt/g/data/MIRROR_A/"

# --- Main Script ---

if [ ! -d "$ROOT_DIR" ]; then
    echo "Error: Root directory '$ROOT_DIR' not found."
    exit 1
fi

echo "Processing directory tree starting from: $ROOT_DIR"
echo "WARNING: This script will delete files. Please ensure you have a backup."
read -p "Type 'yes' to continue: " CONFIRMATION

if [ "$CONFIRMATION" != "yes" ]; then
    echo "Operation cancelled."
    exit 0
fi

# Find all directories and process them one by one
find "$ROOT_DIR" -type d -print0 | while IFS= read -r -d $'\0' dir; do
    # Skip the root directory itself if it's not meant to be processed in this way
    # (i.e., you only want to process subdirectories)
    # if [ "$dir" == "$ROOT_DIR" ]; then
    #     continue
    # fi

    # Find all regular files in the current directory
    # Using 'printf "%s\n"' and 'sort' to ensure consistent ordering
    files_in_dir=$(find "$dir" -maxdepth 1 -type f -print0 | sort -z | xargs -0 -n 1 basename)

    num_files=$(echo "$files_in_dir" | wc -l)

    if [ "$num_files" -gt 1 ]; then
        echo "  Processing directory: $dir"
        # Get the first file (alphabetically after sorting)
        file_to_keep=$(echo "$files_in_dir" | head -n 1)

        echo "    Keeping: $file_to_keep"

        # Loop through all files again and delete those that are not the one to keep
        echo "$files_in_dir" | while IFS= read -r file_to_check; do
            if [ "$file_to_check" != "$file_to_keep" ]; then
                full_path_to_delete="$dir/$file_to_check"
                if [ -f "$full_path_to_delete" ]; then
                    echo "      Deleting: $full_path_to_delete"
                    rm "$full_path_to_delete"
                fi
            fi
        done
    elif [ "$num_files" -eq 1 ]; then
        echo "  Directory '$dir' already has only one file. Skipping."
    else
        echo "  Directory '$dir' is empty or contains no regular files. Skipping."
    fi
done

echo "Script finished."
