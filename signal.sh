# A helper bash script for https://github.com/thephm/signal_sqlite_md
# Run this in WSL ubunu shell
# To install WSL: https://learn.microsoft.com/en-us/windows/wsl/install

# this is your slug
ME=bernie

# location of 'signalbackup-tools_win.exe'
DIR=/mnt/c/Users/micro/OneDrive/Desktop

# where you place the exported SQLite output files in steps 6 and 8
DATA_DIR=/mnt/c/data/signal_sqlite

# location of the Python script
PY_DIR=/mnt/c/data/github/signal_sqlite_md

# configuration for signal_sqlite_md
CONFIG_DIR=/mnt/c/data/dev-output/config

# location to put the output Markdown files from signal_sqlite_md
OUTPUT_DIR=/mnt/c/data/dev-output

source .venv/bin/activate

# get the SQLite DB key
SIGNAL_BACKUP_TOOL="$DIR/signalbackup-tools_win.exe"
if [ ! -f "$SIGNAL_BACKUP_TOOL" ]; then
	echo "Missing executable: $SIGNAL_BACKUP_TOOL"
	echo "Update DIR in signal.sh to the folder containing signalbackup-tools_win.exe"
	exit 1
fi
"$SIGNAL_BACKUP_TOOL" --showdesktopkey --ignorewal

echo ""
echo "1. Launch SQL C:\\ProgramData\\Microsoft\\Windows\\Start Menu\\Programs\\DB Browser (SQLCipher)"
echo "2. Click 'Open Database' button"
echo "3. Open C:\\Users\\micro\\AppData\\Roaming\\Signal\\sql\\db.sqlite"
echo "4. Choose Raw Option"
echo "5. Type 0x followed by the key from above"
echo "6. Right-click on messages and 'export as CSV file'"
echo "7. Click 'Save'"
echo "8. Right-click on conversations and 'export as CSV file'"
echo "9. Click 'Save'"
echo "10. Come back here!"
echo ""

# Pause and wait for the user to press Enter
read -p "Press Enter to continue..."

cd "$PY_DIR" || exit 1
python3 signal_sqlite_md.py -c "$CONFIG_DIR" -s "$DATA_DIR" -f "$DATA_DIR/messages.csv" -d -o "$OUTPUT_DIR" -m "$ME" -b 1900-01-01
