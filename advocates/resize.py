import os
from PIL import Image

# Directory to scan
dir_path = '.'

# Iterate over each file in directory
for filename in os.listdir(dir_path):
    if filename.endswith('.jpg'):
        filepath = os.path.join(dir_path, filename)

        # Check if file size > 500 KB
        if os.path.getsize(filepath) > 150000:

            # Backup the original file
            backup_filepath = filepath + ".bak"
            os.rename(filepath, backup_filepath)

            # Open the image using PIL
            with Image.open(backup_filepath) as img:
                
                # Calculate new height to maintain aspect ratio
                aspect_ratio = img.height / img.width
                new_height = int(600 * aspect_ratio)
                
                # Resize and save
                img_resized = img.resize((600, new_height))
                img_resized.save(filepath)

print("Processing complete.")
