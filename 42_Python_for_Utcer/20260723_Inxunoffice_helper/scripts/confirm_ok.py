# -*- coding: utf-8 -*-

import os, sys

# this script is designed to rename all files in a specified input directory to have a "_OK" suffix before the file extension.

# get the input directory from command line arguments
if len(sys.argv) != 2:
    print("Usage: python confirm_ok.py <input_directory>")
    sys.exit(1)

input_directory = sys.argv[1]

# check if there are multiple input directories
if os.path.isfile(input_directory):
    # read the input directory from the file
    with open(input_directory, 'r', encoding='utf-8') as f:
        input_directories = f.read().strip().splitlines()
    print(f"\nInput directories loaded from {input_directory}:\n {input_directories}")
else:
    # if the input directory is not a file, check if it is a valid directory
    if not os.path.isdir(input_directory):
        print(f"Error: Input directory does not exist - {input_directory}")
        sys.exit(1)
    else:
        input_directories = [input_directory]
        print(f"\nInput directory: {input_directory}")

# search through Word documents in the input directory
count_renamed = 0
count_skipped = 0
count_failed = 0
print("") # print a blank line for better readability
for input_directory in input_directories:
    for filename in os.listdir(input_directory):
        if filename.endswith('.docx') or filename.endswith('.doc') or filename.endswith('.xlsx') or filename.endswith('.xls'):
            file_path = os.path.join(input_directory, filename)
            # print(f"Renaming {file_path}...")
            # split the filename into name and extension
            name, ext = os.path.splitext(filename)
            # rename the file
            if name.endswith('_OK'):
                print(f"[SKIPPED] File {file_path} already has '_OK' suffix. Skipping rename.")
                count_skipped += 1
                continue
            new_filename = f"{name}_OK{ext}"
            new_file_path = os.path.join(input_directory, new_filename)
            try:
                os.rename(file_path, new_file_path)
                print(f"[SUCCESS] File renamed to {new_file_path}")
                count_renamed += 1
            except Exception as e:
                print("") # print a blank line for better readability
                print(f"[WARNING] Failed to rename file {file_path}: {e}")
                print("")
                count_failed += 1

# print summary of renamed files
print(f"\nSummary:")
print(f"Total files renamed: {count_renamed}")
print(f"Total files skipped: {count_skipped}")
print(f"Total files failed to rename: {count_failed}")