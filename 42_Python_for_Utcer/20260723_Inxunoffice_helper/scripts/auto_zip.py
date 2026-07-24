# -*- coding: utf-8 -*-

import os, sys, shutil
import zipfile

# this script is designed to collect all files in a specified input directory and zip them into a specified output directory.

# get the input and output directories from command line arguments
if len(sys.argv) != 3:
    print("Usage: python auto_zip.py <input_directory> <output_directory>")
    sys.exit(1)

input_directory = sys.argv[1]
output_directory = sys.argv[2]

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

# search through files in the input directory
count_packages = 0
count_files = 0
print("") # print a blank line for better readability
for input_directory in input_directories:
    # find specific folder name: updated_word and updated_excel
    root_path = os.path.abspath(input_directory)
    root_folder_name = os.path.basename(root_path)
    # create a temp folder to hold the files to be zipped
    temp_folder = os.path.join(root_path, 'temp_zip')
    temp_path_list = []
    # clean up existing temp folder if it exists
    if os.path.exists(temp_folder):
        for filename in os.listdir(temp_folder):
            file_path = os.path.join(temp_folder, filename)
            os.remove(file_path)
    else:
        os.makedirs(temp_folder)
    for folder_name in ['updated_word', 'updated_excel']:
        folder_path = os.path.join(input_directory, folder_name)
        if os.path.isdir(folder_path):
            for filename in os.listdir(folder_path):
                # if filename.endswith('.docx') or filename.endswith('.doc') or filename.endswith('.xlsx') or filename.endswith('.xls'):
                file_path = os.path.join(folder_path, filename)
                # copy the file to the temp folder
                temp_file_path = os.path.join(temp_folder, filename)
                shutil.copy2(file_path, temp_file_path)
                temp_path_list.append(temp_file_path)
                count_files += 1
    # create a zip file for the current input directory
    zip_file_name = f"Chapter_{root_folder_name}.zip"
    zip_file_path = os.path.join(output_directory, zip_file_name)
    # clean up existing zip file if it exists
    if os.path.exists(zip_file_path):
        os.remove(zip_file_path)
        print(f"\nExisting zip file removed: {zip_file_path}")
    else:
        print("") # print a blank line for better readability
    print(f"Creating zip file: {zip_file_path}")
    # create a zip file and add the files to it
    try:
        with zipfile.ZipFile(zip_file_path, 'w') as zipf:
            for temp_file_path in temp_path_list:
                zipf.write(temp_file_path, arcname=os.path.basename(temp_file_path))
            count_packages += 1
    except Exception as e:
        print("") # print a blank line for better readability
        print(f"[WARNING] Failed to create zip file {zip_file_path}: {e}")
        print("")

# print summary of renamed files
print(f"\nSummary:")
print(f"Total packages created: {count_packages}")
print(f"Total files included: {count_files}")