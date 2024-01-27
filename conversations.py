import os
import csv

import sys
sys.path.insert(1, '../message_md/')
import person

CONVERSATIONS_FILENAME = "conversations.csv"

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
    CONVERSATION_ID, CONVERSATION_ID, CONVERSATION_JSON, 
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
#   - fieldMap - where the result goes
#
# -----------------------------------------------------------------------------
def parseConversationsHeader(row, fieldMap):

    global ConversationsFields

    count = 0
    for col in row:
        for field in ConversationsFields:
            if col == field:
                fieldMap.append( [field, count] )
        count += 1

# -----------------------------------------------------------------------------
# Find the index for specific CSV field based from the `fieldMap`` on it's label
#
# Parameters:
#
#   - fieldLabel - the field label e.g. SIGNAL_SENT_AT
#   - fieldMap - where the result goes
#
# -----------------------------------------------------------------------------
def fieldIndex(fieldLabel, fieldMap):

    result = -1

    for field in fieldMap:
        if field[0] == fieldLabel:
            result = field[1]
            break

    return result

# -----------------------------------------------------------------------------
#
# Parse the Signal SQLite 'conversations.csv' file to get each person's
# conversation-id since those, not their phone number, is what is in the 
# `messages.csv` export.
#
# Parameters:
#
#   - theConfig - the configuration of the tool in `Config` object
#
# Notes:
#
#    - assumes the first row is the header row. If not, unpredictable results
#      will occur 😂
#
# -----------------------------------------------------------------------------
def parseConversationsFile(theConfig):

    fieldMap = []

    global SignalFields
  
    try:
        fileName = os.path.join(theConfig.sourceFolder, CONVERSATIONS_FILENAME)
        
        with open(fileName, newline='') as conversationsFile:

            conversationsReader = csv.reader(conversationsFile)
            count = 0
            for row in conversationsReader:
                if count == 0:
                    parseConversationsHeader(row, fieldMap)
                else:
                    storeConversationId(theConfig, fieldMap, row)
                count += 1

    except Exception as e:
        print(e)
        return

# -----------------------------------------------------------------------------
#
# Grab the conversation ID from the row and store it in the corresponding
# Person object so it can be used later.
#
# Parameters:
#
#   - theConfig - the configuration of the tool in `Config` object
#   - fieldMap - mapping of the headers to the fields
#   - row - a row from the `conversations` CSV file
#
# -----------------------------------------------------------------------------
def storeConversationId(theConfig, fieldMap, row):

    e164 = row[fieldIndex(CONVERSATION_E164, fieldMap)]
    phone = e164[-10:]
    
    thePerson = person.Person()

    id = row[fieldIndex(CONVERSATION_ID, fieldMap)]

    try:
        thePerson = theConfig.getPersonByNumber(phone)
        if thePerson:
            thePerson.conversationId = id

    except:
        print('could not find:' + str(phone))
