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

import sys
sys.path.insert(1, '../message_md/')
import person
import message
import attachment
import signal_message
import config

ATTACHMENTS_FILENAME = "message_attachments.csv"

# As at 2025-06-28 there are 57 fields in the `message_attachments.csv` file 
# but we only need a few of them. The rest are not used in this tool.

ATTACHMENT_MESSAGE_ID = "messageId"
ATTACHMENT_CONVERSATION_ID = "conversationId"
ATTACHMENT_CONTENT_TYPE = "contentType"
ATTACHMENT_SIZE = "size"
ATTACHMENT_HEIGHT = "height"
ATTACHMENT_WIDTH = "width"

AttachmentsFields = [
    ATTACHMENT_MESSAGE_ID,
    ATTACHMENT_CONVERSATION_ID, 
    ATTACHMENT_CONTENT_TYPE,
    ATTACHMENT_HEIGHT,
    ATTACHMENT_WIDTH,
    ATTACHMENT_SIZE
]

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
    the_attachment = attachment.Attachment()

    id = row[field_index(ATTACHMENT_MESSAGE_ID, field_map)]

    the_message = next((m for m in messages if m.id == id), None)

    size = int(float(row[field_index(ATTACHMENT_SIZE, field_map)]))
    height = int(float(row[field_index(ATTACHMENT_HEIGHT, field_map)]))
    width = int(float(row[field_index(ATTACHMENT_WIDTH, field_map)]))
    content_type = row[field_index(ATTACHMENT_CONTENT_TYPE, field_map)]

    the_attachment.type = content_type
    the_attachment.size = size
    the_attachment.filename = "unknown.jpg"
    the_attachment.id = "unknown"
    the_attachment.height = height
    the_attachment.width = width

    the_message.attachments.append(the_attachment)
        
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

    global SignalFields
  
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
