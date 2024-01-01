# Copy all the Signal attachment files from it's various subfolders into
# a single folder. 
#
# ChatGPT helped me with this!
#
# I use this in ubuntu running on Windows Subsystem for Linux (WSL)
#
# Shouldn't it be a BATch file in Windows Powershell? Probably
#
# In this example, the user is `micro`

# Source folder (change accordingly)
SOURCE_FOLDER="/mnt/c/Users/micro/AppData/Roaming/Signal/attachments.noindex"

# Destination folder (change accordingly)
DESTINATION_FOLDER="/mnt/c/data/signal_sqlite/attachments"

# Create destination folder if it doesn't exist
mkdir -p "$DESTINATION_FOLDER"

# Find all files in subfolders of the source folder and copy them to the destination folder
find "$SOURCE_FOLDER" -type f -exec cp {} "$DESTINATION_FOLDER" \;

echo "Files copied successfully from $SOURCE_FOLDER to $DESTINATION_FOLDER"
