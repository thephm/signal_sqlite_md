# -----------------------------------------------------------------------------
# 
# Code related to the Signal SQLite `conversations` table/CSV export.
#
# Conversations are like contacts. There are individual records for a person
# and records for each group of people.
#
# Use the `serviceId` field in `conversations` and the `sourceServiceId` in
# `messages` to correlate them.
#
# -----------------------------------------------------------------------------

import os
import csv
import json
import re
import logging

import sys
sys.path.insert(1, '../hal/')
import person
import identity
sys.path.insert(1, '../message_md/')
import config

CONVERSATIONS_FILENAME = "conversations.csv"
MESSAGES_FILENAME = "messages.csv"

# As at 2024, these are the columns/fields:
#
# id,json,active_at,type,members,name,profileName,profileFamilyName,
# profileFullName,e164,serviceId,groupId,profileLastFetchedAt

CONVERSATION_ID = "id"
CONVERSATION_JSON = "json"
CONVERSATION_ACTIVE_AT = "active_at"
CONVERSATION_TYPE = "type"
CONVERSATION_MEMBERS = "members"
CONVERSATION_NAME = "name"
CONVERSATION_PROFILE_NAME = "profileName"
CONVERSATION_PROFILE_FAMILY_NAME = "profileFamilyName"
CONVERSATION_PROFILE_FULL_NAME = "profileFullName"
CONVERSATION_E164 = "e164"
CONVERSATION_SERVICE_ID = "serviceId"
CONVERSATION_GROUP_ID = "groupId"
CONVERSATION_PROFILE_LAST_FETCHED_AT = "profileLastFetchedAt"

ConversationsFields = [
    CONVERSATION_ID, CONVERSATION_JSON, 
    CONVERSATION_ACTIVE_AT, CONVERSATION_TYPE, CONVERSATION_MEMBERS,
    CONVERSATION_NAME, CONVERSATION_PROFILE_NAME, 
    CONVERSATION_PROFILE_FAMILY_NAME, CONVERSATION_PROFILE_FULL_NAME,
    CONVERSATION_E164, CONVERSATION_SERVICE_ID, CONVERSATION_GROUP_ID, 
    CONVERSATION_PROFILE_LAST_FETCHED_AT 
]

# -----------------------------------------------------------------------------
#
# Parse the header row of the `conversations.csv` file and map it to the fields
#
# Parameters:
#
#   - row - the header row
#   - field_map - where the result goes
#
# -----------------------------------------------------------------------------
def parse_conversations_header(row, field_map):

    global ConversationsFields

    count = 0
    for col in row:
        for field in ConversationsFields:
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

def get_slug(full_name):
    """
    Convert a full name string to a slug suitable for use in URLs or filenames.
    
    Parameters:
    - full_name: The full name string, e.g., "Bob Smith"
    
    Returns:
    - A slugified version of the full name, e.g., "bob_smith"
    """

    # replace spaces and slashes with underscores first
    slug = re.sub(r'[ /]+', '_', full_name)

    # insert underscores before capital letters and convert to lowercase
    slug = re.sub(r'(?<!^)(?=[A-Z])', '_', slug).lower()

    # remove double underscores
    slug = re.sub(r'_+', '_', slug)

    return slug

def get_last_name(full_name):
    """
    Get the last name from a full name string, capitalizing it.

    Parameters:
    - full_name: The full name string, e.g., "Bob Smith" or "Marc-André".

    Returns:
    - The last name, capitalized, e.g., "Smith"
    """

    # split the full name by spaces
    name_parts = full_name.split()
    
    # if there is only one word (no spaces), return an empty string
    if len(name_parts) == 1:
        return ''
    else: 
        # return the last element of the list as the last name
        return name_parts[-1].capitalize() if name_parts else ''
    
def get_first_name(name):
    """
    Get the first name from a full name string, handling cases with hyphens.
        
    Parameters:
    - name: The full name string, e.g., "Marc-André".
    
    Returns:
    - The first name, capitalized, e.g., "Marc".
    """

    # get the text up to the first space
    name = name.split()[0]

    # split it into words if there are '-' e.g. "marc-andre"
    parts = name.split('-')

    # capitalize the words e.g. "Marc" and "Andre"
    capitalized_parts = [part.capitalize() for part in parts]

    # join them back together e.g. "Marc-Andre"
    return '-'.join(capitalized_parts)

def store_conversation_info(the_config, field_map, row, active_conversation_ids):
    """
    Grab the conversation info from the row and store it in the corresponding
    Person object so it can be used later.
    
    Parameters:
    - the_config: Configuration object with source folder and other settings.       
    - field_map: List mapping field names to their indices in the CSV row.
    - row: List representing a row from the `conversations.csv` file.

    Returns:
    - None

    Notes:
    - 4 x name columns: `name, profileName, familyName, fullName`
    - in my file there are 45, 30, 16, 30 of them, respectively
    - sometimes the `profileName` and `fullName` are the same (qty 9) but in 
      other cases, it's just their first name (qty 14)
    - SO, if the person can't be found by their phone number, and the option
      to create people on the fly is True, take the `fullName` first, making
      it snake_case. If it doesn't exist, then use `profileName`. If no 
      profileName is found, ignore it
    """

    e164 = row[field_index(CONVERSATION_E164, field_map)]
    phone = e164[-10:]
    slug = ""
    
    id = row[field_index(CONVERSATION_ID, field_map)]
    conversation_type = row[field_index(CONVERSATION_TYPE, field_map)]

    if conversation_type == "private" and active_conversation_ids is not None and id not in active_conversation_ids:
        return

    # grab the name fields
    profile_name = row[field_index(CONVERSATION_PROFILE_NAME, field_map)]
    full_name = row[field_index(CONVERSATION_PROFILE_FULL_NAME, field_map)]

    # first, see if we can find the person using their phone number
    try:
        the_person = the_config.get_person_by_number(phone)
    except:
        pass

    # if couldn't find them with the phone number, try their profile full name
    if not the_person and full_name:
        the_person = the_config.get_person_by_full_name(full_name)

        # if the option to create people on the fly who are not in  
        # the `people.json` file, use the `fullName` or `profileName`
        if the_config.create_people and not the_person:
            the_person = the_config.get_or_create_person(
                full_name=full_name or profile_name,
                mobile=e164,
                conversation_id=id,
                source="Signal",
                prompt=True,
            )
        elif the_config.create_people and the_person:
            if e164 and not the_person.contact.mobile:
                the_person.contact.mobile = the_config.normalize_mobile(e164)
            if id and not the_person.conversation_id:
                the_person.conversation_id = id

    # get the `ServiceId` value which me thinks is the unique ID for person.
    # this is needed to figure out who replied to group messages as those 
    # don't include a phone number of the sender
    data = row[field_index(CONVERSATION_JSON, field_map)]

    try:
        json_data = json.loads(data)
    except Exception as e:
        logging.error(f"store_conversation_info {id}: {e}")

    if the_person:
        the_person.conversation_id = id
        the_person.identity.full_name = full_name
        try:
            the_person.service_id = json_data[CONVERSATION_SERVICE_ID]
        except Exception as e:
            # groups don't have a service_id field
            pass
    else:
        group_slug = the_config.get_group_slug_by_conversation_id(id)
        
def load_active_conversation_ids(the_config):
    """Return conversation IDs used by exported messages or their reactions."""
    try:
        filename = os.path.join(the_config.source_folder, MESSAGES_FILENAME)
        with open(filename, newline='') as messages_file:
            reader = csv.DictReader(messages_file)
            conversation_ids = set()
            for row in reader:
                conversation_id = row.get("conversationId", "").strip()
                if conversation_id and row.get("type") in {"incoming", "outgoing"}:
                    conversation_ids.add(conversation_id)

                try:
                    message_data = json.loads(row.get("json", ""))
                    for reaction in message_data.get("reactions", []):
                        from_id = str(reaction.get("fromId", "")).strip()
                        if from_id:
                            conversation_ids.add(from_id)
                except (TypeError, ValueError):
                    pass

            return conversation_ids
    except Exception as e:
        logging.warning(f"load_active_conversation_ids failed: {e}")
        return None

def parse_conversations_file(the_config):
    """
    Parse the Signal SQLite 'conversations.csv' file to get each person's
    conversation-id since those, not their phone number, is what is in the 
    `messages.csv` export.
        
    Parameters:
    - the_config: The configuration object containing the source folder and other settings.

    Returns:
    - None

    Notes:
    - assumes the first row is the header row. If not, unpredictable results
      will occur 😂
    """

    field_map = []
    active_conversation_ids = load_active_conversation_ids(the_config)

    global SignalFields
  
    try:
        filename = os.path.join(the_config.source_folder, CONVERSATIONS_FILENAME)
        
        with open(filename, newline='') as conversations_file:

            conversations_reader = csv.reader(conversations_file)
            count = 0
            for row in conversations_reader:
                if count == 0:
                    parse_conversations_header(row, field_map)
                else:
                    try:
                        store_conversation_info(the_config, field_map, row, active_conversation_ids)
                    except Exception as e:
                        logging.error(f"parse_conversations_file failed: {e}")
                count += 1

    except Exception as e:
        logging.error(f"parse_conversations_file failed: {e}")
        return
