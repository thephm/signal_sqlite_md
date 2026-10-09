# -----------------------------------------------------------------------------
# 
# Code related to the Signal SQLite `message_attachments` table/CSV export.
#
# Attachments date includes a `messageId` which is used to tie a specific
# attachment back to a message between people. 
#
# The actual attachment is not stored in the CSV file, rather it is on the
# local filesystem in encrypted form. The CSV file contains the metadata.
#
# -----------------------------------------------------------------------------

import os
import csv
import logging
from datetime import datetime
from pathlib import PurePath, PureWindowsPath

import sys
sys.path.insert(1, '../message_md/')
import person
import message
import attachment
import signal_message
import config

ATTACHMENTS_FILENAME = "message_attachments.csv"
MISSING_MESSAGE_IDS_WARNED = set()


def image_link_width(filename, the_config):
    if PurePath(filename).name.lower().startswith("screenshot"):
        return 250
    return the_config.image_width

# As at 2025-06-28 there are 57 fields in the `message_attachments.csv` file 
# but we only need a few of them. The rest are not used in this tool.

ATTACHMENT_MESSAGE_ID = "messageId"
ATTACHMENT_CONVERSATION_ID = "conversationId"
ATTACHMENT_CONTENT_TYPE = "contentType"
ATTACHMENT_SENT_AT = "sentAt"
ATTACHMENT_ORDER_IN_MESSAGE = "orderInMessage"
ATTACHMENT_SIZE = "size"
ATTACHMENT_HEIGHT = "height"
ATTACHMENT_WIDTH = "width"
ATTACHMENT_FILE_NAME_CANDIDATES = [
    "fileName",
    "filename",
    "file_name",
    "name",
]

AttachmentsFields = [
    ATTACHMENT_MESSAGE_ID,
    ATTACHMENT_CONVERSATION_ID, 
    ATTACHMENT_CONTENT_TYPE,
    ATTACHMENT_SENT_AT,
    ATTACHMENT_ORDER_IN_MESSAGE,
    ATTACHMENT_HEIGHT,
    ATTACHMENT_WIDTH,
    ATTACHMENT_SIZE
] + ATTACHMENT_FILE_NAME_CANDIDATES

class SignalAttachment(attachment.Attachment):
    def generate_link(self, the_config):
        filename = self.custom_filename or self.filename
        if not filename:
            return super().generate_link(the_config)

        link = ""
        if self.is_image() and the_config.image_embed:
            link = "!"
        link += "[[" + filename
        if self.is_image() and the_config.image_width:
            link += "|" + str(image_link_width(filename, the_config))
        link += "]]" + "\n"
        return link

def parse_attachments_header(row, field_map):
    """
    Parse the header row of the `message_attachments.csv` file and map it to
    the fields defined in `AttachmentsFields`.
    
    Populates the `field_map` with tuples of field names and the corresponding 
    indices in the CSV row.
    
    Parameters:
    - row: The header row from the CSV file.
    - field_map: A list to store the mapping of field names to their indices.

    Returns:
    - None
    """

    global AttachmentsFields

    count = 0
    for col in row:
        for field in AttachmentsFields:
            if col == field:
                field_map.append( [field, count] )
        count += 1
def field_index(field_label, field_map):
    """
    Find the index of a specific field in the `field_map` based on its label.

    Parameters:
    - field_label: Label of the field to find e.g., ATTACHMENT_CONTENT_TYPE
    - field_map: List mapping field names to their indices in the CSV row.

    Returns:
    - The index of the field if found, otherwise -1.
    """

    result = -1

    for field in field_map:
        if field[0] == field_label:
            result = field[1]
            break

    return result

def optional_field_value(row, field_map, field_labels):
    for field_label in field_labels:
        index = field_index(field_label, field_map)
        if index != -1 and index < len(row):
            value = row[index].strip()
            if value:
                return value
    return ""

def filename_from_path(value):
    value = (value or "").strip().strip('"')
    if not value:
        return ""
    return PurePath(PureWindowsPath(value).name).name

def extension_from_content_type(content_type):
    content_type = (content_type or "").split(";", 1)[0].strip().lower()
    extensions = {
        "image/jpeg": "jpg",
        "image/jpg": "jpg",
        "image/png": "png",
        "image/gif": "gif",
        "image/heic": "heic",
        "image/heif": "heif",
        "image/webp": "webp",
        "video/mp4": "mp4",
        "video/quicktime": "mov",
        "video/webm": "webm",
        "audio/mpeg": "mp3",
        "audio/mp4": "mp4",
        "audio/aac": "aac",
        "audio/x-m4a": "m4a",
    }
    return extensions.get(content_type, "bin")

def signal_default_filename(sent_at, order_in_message, content_type):
    try:
        timestamp_ms = int(float(sent_at))
        timestamp = datetime.fromtimestamp(timestamp_ms / 1000)
        timestamp_text = timestamp.strftime("%Y-%m-%d-%H-%M-%S") + f"-{timestamp_ms % 1000:03d}"
    except Exception:
        timestamp_text = "unknown"

    try:
        suffix_index = int(float(order_in_message)) + 2
    except Exception:
        suffix_index = 2

    return f"signal-{timestamp_text}_{suffix_index:03d}.{extension_from_content_type(content_type)}"

# Attachments that arrive repeatedly under the same name, e.g. a daily image.
# These get the message's sent date appended (" YYYY-MM-DD") so every copy has
# a unique filename. Matching is case-insensitive.
DATED_FILENAME_EXCEPTIONS = {
    "spelling bee hints.jpg",
}

def needs_dated_filename(filename):
    return PurePath(filename).name.lower() in DATED_FILENAME_EXCEPTIONS

def dated_filename(filename, sent):
    """Append ' YYYY-MM-DD' (from datetime `sent`) to exception filenames."""
    if sent is None or not needs_dated_filename(filename):
        return filename
    path = PurePath(filename)
    return f"{path.stem} {sent.strftime('%Y-%m-%d')}{path.suffix}"

def sent_at_to_datetime(sent_at):
    """Convert a Signal `sentAt` millisecond value to a local datetime, or None."""
    try:
        return datetime.fromtimestamp(int(float(sent_at)) / 1000)
    except (TypeError, ValueError, OverflowError, OSError):
        return None

def apply_filename_exceptions(filename, sent_at, fallback_timestamp=None):
    if not needs_dated_filename(filename):
        return filename
    sent = sent_at_to_datetime(sent_at)
    if sent is None and fallback_timestamp:
        sent = datetime.fromtimestamp(fallback_timestamp)
    if sent is None:
        logging.warning(f"No sent date for attachment '{filename}'; keeping its original name.")
        return filename
    return dated_filename(filename, sent)

def preserve_exact_filename(the_attachment, filename, content_type, the_config):
    filename = filename_from_path(filename)
    if not filename:
        the_attachment.id = "untitled"
        return

    the_attachment.id = PurePath(filename).stem
    the_attachment.filename = filename
    the_attachment.custom_filename = filename

def has_duplicate_attachment(the_message, candidate):
    candidate_key = (
        candidate.id,
        candidate.filename,
        candidate.type,
        candidate.size,
        candidate.height,
        candidate.width,
    )
    for existing in the_message.attachments:
        existing_key = (
            existing.id,
            existing.filename,
            existing.type,
            existing.size,
            existing.height,
            existing.width,
        )
        if existing_key == candidate_key:
            return True
    return False

def store_attachments_info(messages, the_config, field_map, row):
    """
    Store the attachment information from a row in the `message_attachments.csv`
    file into the configuration object.

    Parameters:
    - messages: List of Messages to which attachments will be added to.
    - the_config: Configuration object with source folder and other settings.
    - field_map: List mapping field names to their indices in the CSV row.
    - row: List representing a row from the `message_attachments.csv` file.

    Returns:
    - None
    """
    the_attachment = SignalAttachment()

    id = row[field_index(ATTACHMENT_MESSAGE_ID, field_map)]

    the_message = next((m for m in messages if m.id == id), None)

    # Handle empty strings in numeric fields by defaulting to 0
    size_str = row[field_index(ATTACHMENT_SIZE, field_map)]
    size = int(float(size_str)) if size_str and size_str.strip() else 0
    
    height_str = row[field_index(ATTACHMENT_HEIGHT, field_map)]
    height = int(float(height_str)) if height_str and height_str.strip() else 0
    
    width_str = row[field_index(ATTACHMENT_WIDTH, field_map)]
    width = int(float(width_str)) if width_str and width_str.strip() else 0
    
    content_type = row[field_index(ATTACHMENT_CONTENT_TYPE, field_map)]
    sent_at = optional_field_value(row, field_map, [ATTACHMENT_SENT_AT])
    filename = optional_field_value(row, field_map, ATTACHMENT_FILE_NAME_CANDIDATES)
    if filename:
        message_timestamp = getattr(the_message, "timestamp", None) if the_message is not None else None
        filename = apply_filename_exceptions(filename_from_path(filename), sent_at, message_timestamp)
    else:
        order_in_message = optional_field_value(row, field_map, [ATTACHMENT_ORDER_IN_MESSAGE])
        filename = signal_default_filename(sent_at, order_in_message, content_type)

    the_attachment.type = content_type
    the_attachment.size = size
    preserve_exact_filename(the_attachment, filename, content_type, the_config)
    the_attachment.height = height
    the_attachment.width = width

    if the_message is not None:
        if not has_duplicate_attachment(the_message, the_attachment):
            the_message.attachments.append(the_attachment)
    else:
        if id not in MISSING_MESSAGE_IDS_WARNED:
            MISSING_MESSAGE_IDS_WARNED.add(id)
            logging.warning(f"No message found with id {id} for attachment.")

def parse_attachments_file(messages, the_config):
    """
    Parse the Signal SQLite `message_attachments.csv` file to extract attachment
    metadata and store it in the configuration object.

    Parameters:
    - messages: List of Messages to which attachments will be added to.
    - the_config: Configuration object containing source folder and other settings.

    Returns:
    - None
    """

    field_map = []

    global AttachmentsFields
  
    try:
        filename = os.path.join(the_config.source_folder, ATTACHMENTS_FILENAME)
        
        with open(filename, newline='') as attachments_file:

            attachments_reader = csv.reader(attachments_file)
            count = 0
            for row in attachments_reader:
                if count == 0:
                    parse_attachments_header(row, field_map)
                else:
                    try:
                        store_attachments_info(messages, the_config, field_map, row)
                    except Exception as e:
                        logging.error(f"store_attachments_info failed: {e}")
                count += 1

    except Exception as e:
        logging.error(f"parse_attachments_file failed: {e}")
        return

def load_attachment_message_ids(the_config):
    """Return the message IDs represented in the attachment metadata export."""
    try:
        filename = os.path.join(the_config.source_folder, ATTACHMENTS_FILENAME)
        with open(filename, newline='') as attachments_file:
            return {
                row.get(ATTACHMENT_MESSAGE_ID, "").strip()
                for row in csv.DictReader(attachments_file)
                if row.get(ATTACHMENT_MESSAGE_ID, "").strip()
            }
    except Exception as e:
        logging.error(f"load_attachment_message_ids failed: {e}")
        return set()
