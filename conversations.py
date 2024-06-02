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
# Grab the conversation info from the row and store it in the corresponding
# Person object so it can be used later.
#
# Parameters:
#
#   - the_config - the configuration of the tool in `Config` object
#   - field_map - mapping of the headers to the fields
#   - row - a row from the `conversations` CSV file
#
# -----------------------------------------------------------------------------
def store_conversation_info(the_config, field_map, row):

    the_person = person.Person()

    e164 = row[field_index(CONVERSATION_E164, field_map)]
    phone = e164[-10:]
    
    id = row[field_index(CONVERSATION_ID, field_map)]
    full_name = row[field_index(CONVERSATION_PROFILE_FULL_NAME, field_map)]

    # first, see if we can find the person using their phone number
    try:
        the_person = the_config.get_person_by_number(phone)
    except:
        pass
        
    # if couldn't find them with the phone number, try their profile full name
    if not the_person:
        try:
            the_person = the_config.get_person_by_full_name(full_name)
        except Exception as e:
            print(e)
            print("Could not find a person with phone '" + str(phone) + "' " )
            if len(full_name):
                print("or by full name: '" + full_name + "'")

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
