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

import sys
sys.path.insert(1, '../message_md/')
import person

CONVERSATIONS_FILENAME = "conversations.csv"

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

# -----------------------------------------------------------------------------
#
# Find the index for specific CSV field based from the `field_map`` on it's 
# field label.
#
# Parameters:
#
#   - field_label - the field label e.g. SIGNAL_SENT_AT
#   - field_map - where the result goes
#
# -----------------------------------------------------------------------------
def field_index(field_label, field_map):

    result = -1

    for field in field_map:
        if field[0] == field_label:
            result = field[1]
            break

    return result

# -----------------------------------------------------------------------------
#
# Convert a person's name to a slug.
#
# Parameters:
#
#   - full_name - person's full name e.g. "Bob Smith"
#
# Returns:
# 
#   - slug of the name e.g. "bob_smith"
#
# -----------------------------------------------------------------------------
def get_slug(full_name):

    # replace spaces and slashes with underscores first
    slug = re.sub(r'[ /]+', '_', full_name)

    # insert underscores before capital letters and convert to lowercase
    slug = re.sub(r'(?<!^)(?=[A-Z])', '_', slug).lower()

    # remove double underscores
    slug = re.sub(r'_+', '_', slug)

    return slug

# -----------------------------------------------------------------------------
#
# Get a person's last name from their full name.
#
# Parameters:
#
#   - full_name - person's full name e.g. "Bob Smith"
#
# Returns:
#
#   - the righmost part of the string after the last space e.g. "Smith"
#
# -----------------------------------------------------------------------------
def get_last_name(full_name):

    # split the full name by spaces
    name_parts = full_name.split()
    
    # if there is only one word (no spaces), return an empty string
    if len(name_parts) == 1:
        return ''
    else: 
        # return the last element of the list as the last name
        return name_parts[-1].capitalize() if name_parts else ''
    
# -----------------------------------------------------------------------------
#
# Get a person's first name from their full name.
#
# Parameters:
#
#   - full_name - person's full name e.g. "Bob Smith"
#
# Returns:
#
#   - the first word e.g. "Bob"
#
# -----------------------------------------------------------------------------
def get_first_name(name):

    # get the text up to the first space
    name = name.split()[0]

    # split it into words if there are '-' e.g. "marc-andre"
    parts = name.split('-')

    # capitalize the words e.g. "Marc" and "Andre"
    capitalized_parts = [part.capitalize() for part in parts]

    # join them back together e.g. "Marc-Andre"
    return '-'.join(capitalized_parts)

# -----------------------------------------------------------------------------
#
# Grab the conversation info from the row and store it in the corresponding
# Person object so it can be used later.
#
# Parameters:
#
#   - the_config - the configuration of the tool in `Config` object
#   - field_map - mapping of the headers to the fields
#   - row - a row from the `conversations` CSV file
#
# Notes:
#
#   - 4 x name columns: `name, profileName, familyName, fullName`
#   - in my file there are 45, 30, 16, 30 of them, respectively
#   - sometimes the `profileName` and `fullName` are the same (qty 9) but in 
#     other cases, it's just their first name (qty 14)
#   - SO, if the person can't be found by their phone number, and the option
#     to create people on the fly is True, take the `fullName` first, making
#     it snake_case. If it doesn't exist, then use `profileName`. If no 
#     profileName is found, ignore it
#
# -----------------------------------------------------------------------------
def store_conversation_info(the_config, field_map, row):

    e164 = row[field_index(CONVERSATION_E164, field_map)]
    phone = e164[-10:]
    slug = ""
    
    id = row[field_index(CONVERSATION_ID, field_map)]

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
        if not the_person and the_config.create_people:
            the_person = person.Person()
            if full_name:
                slug = get_slug(full_name)
                first_name = get_first_name(full_name)
            elif profile_name:
                slug = get_slug(profile_name)
                first_name = get_first_name(profile_name)
            if slug:
                # add the person to the config
                the_person.slug = slug
                the_person.first_name = first_name.capitalize()
                the_person.last_name = get_last_name(full_name)
                the_person.full_name = the_person.first_name + " " + the_person.last_name.capitalize()
                if e164:
                    the_person.mobile = e164
                the_config.people.append(the_person)
            else:
                print(e)
                print("Could not find a person by phone '" + str(phone) + "' or by full name '" + full_name + "'")

    # get the `ServiceId` value which me thinks is the unique ID for person.
    # this is needed to figure out who replied to group messages as those 
    # don't include a phone number of the sender
    data = row[field_index(CONVERSATION_JSON, field_map)]

    try:
        json_data = json.loads(data)
    except Exception as e:
        print(id + ": " + e)

    if the_person:
        the_person.conversation_id = id
        the_person.full_name = full_name

        try:
            the_person.service_id = json_data[CONVERSATION_SERVICE_ID]
        except Exception as e:
            # groups don't have a service_id field
            pass
        
# -----------------------------------------------------------------------------
#
# Parse the Signal SQLite 'conversations.csv' file to get each person's
# conversation-id since those, not their phone number, is what is in the 
# `messages.csv` export.
#
# Parameters:
#
#   - the_config - the configuration of the tool in `Config` object
#
# Notes:
#
#   - assumes the first row is the header row. If not, unpredictable results
#     will occur 😂
#
# -----------------------------------------------------------------------------
def parse_conversations_file(the_config):

    field_map = []

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
                        store_conversation_info(the_config, field_map, row)
                    except Exception as e:
                        print(e)
                count += 1

    except Exception as e:
        print(e)
        return
