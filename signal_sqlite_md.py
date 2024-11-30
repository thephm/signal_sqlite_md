import csv
import time
import json
from datetime import datetime, timezone
import tzlocal # pip install tzlocal

import sys
import conversations
import signal_message
sys.path.insert(1, '../message_md/')
import message_md
import config
import markdown
import message
import person
import attachment

SIGNAL_ID = "id"           # Unique identifier for the message
SIGNAL_ROW_ID = "rowid"    # Row ID in the SQLite table
SIGNAL_JSON = "json"       # JSON representation of the message
SIGNAL_SENT_AT = "sent_at" # Timestamp when the message was sent
SIGNAL_CONVERSATION_ID = "conversationId" # Identifier for conversation thread
SIGNAL_SOURCE = "source"   # Address (phone number) of the sender/recipient
SIGNAL_HAS_ATTACHMENTS = "hasAttachments" # Whether the message has attachments
SIGNAL_TYPE = "type"       # Type of the message (incoming, outgoing, etc.)
SIGNAL_BODY = "body"       # Content of the message

SIGNAL_INCOMING = "incoming"  # Incoming message from another user
SIGNAL_OUTGOING = "outgoing"  # Outgoing message sent by the user

JSON_REACTIONS = "reactions"
JSON_ATTACHMENTS = "attachments"
JSON_TIMESTAMP = "timestamp"
JSON_SOURCE_SERVICE_ID = "sourceServiceId"  # Service ID of the sender/recipient 
JSON_FROM_ID = "fromId"
JSON_EMOJI = "emoji"
JSON_TARGET_TIMESTAMP = "targetTimestamp"
JSON_ATTACHMENT_CONTENT_TYPE = "contentType"
JSON_ATTACHMENT_FILENAME = "fileName"
JSON_ATTACHMENT_PATH = "path"
JSON_ATTACHMENT_SIZE = "size"
JSON_ATTACHMENT_WIDTH = "width"
JSON_ATTACHMENT_HEIGHT = "height"
JSON_QUOTE = "quote"
JSON_QUOTE_ID = "id"
JSON_QUOTE_TEXT = "text"

# messagesFile = "/mnt/c/data/signal_sqlite/messages.csv"

SignalFields = [
    SIGNAL_ROW_ID, SIGNAL_ID, SIGNAL_JSON, SIGNAL_SENT_AT, 
    SIGNAL_CONVERSATION_ID, SIGNAL_SOURCE, SIGNAL_HAS_ATTACHMENTS, 
    SIGNAL_TYPE, SIGNAL_BODY
]

# As of 2024-09-01 these are the columns in `messages` table
# rowid,id,json,readStatus,expires_at,sent_at,schemaVersion,conversationId,received_at,source,hasAttachments,hasFileAttachments,hasVisualMediaAttachments,expireTimer,expirationStartTimestamp,type,body,messageTimer,messageTimerStart,messageTimerExpiresAt,isErased,isViewOnce,sourceServiceId,serverGuid,sourceDevice,storyId,isStory,isChangeCreatedByUs,isTimerChangeFromSync,seenStatus,storyDistributionListId,expiresAt,isUserInitiatedMessage,mentionsMe,isGroupLeaveEvent,isGroupLeaveEventFromOther,callId,shouldAffectPreview,shouldAffectActivity,isAddressableMessage

# -----------------------------------------------------------------------------
#
# Parse the header row of the `messages.csv` file and map it to the fields
#
# Parameters:
#
#   - row - the header row
#   - field_map - where the result goes
#
# -----------------------------------------------------------------------------
def parse_header(row, field_map):

    global SignalFields

    count = 0
    for col in row:
        for field in SignalFields:
            if col == field:
                field_map.append( [field, count] )
        count += 1

# -----------------------------------------------------------------------------
#
# Find the index for specific CSV field based from the `field_map`` on it's label
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
# Get the filename from "path" attribute in "attachments".
#
# Example:
#
# "path":"97\\977e7e5f43d0c935ad785b290023d1455631351772b2f8c53e5ced4a5f8ffb81"
# 
# returns:
#
# 977e7e5f43d0c935ad785b290023d1455631351772b2f8c53e5ced4a5f8ffb81
#
# -----------------------------------------------------------------------------
def get_filename(str):

    index = str.rfind("\\")
    
    if index != -1:
        result = str[index + 1:]
        return result
    else:
        # if "\\" is not found, return the original string
        return str

# -----------------------------------------------------------------------------
#
# Parse the attachments portion of the `json` message into Attachment objects
# and add them to the Message passed in.
#
# Parameters:
# 
#   - data - the JSON data
#   - the_message - the target Message object where the values will go
#
# Notes:
# 
#   - this part of the message contains metadata about the attachments
#   - the actual content of the messages are stored unencrypted locally
#   - the files are stored in a series of subfolders with a 2 character ID
#   - the files have no file extension
#   - a sample with many fields removed for brevity sake
#   - there's also a 150x150 pixel "thumbnail" stored but not interested
#
#   ""attachments"":[{
#       ""contentType"":""image/png"",
#       ""fileName"":""image.png"",
#       ""path"":""97\\977e7e5f43d0c935ad785b290023d1455631351772b2f8c53e5ced4a5f8ffb81"",
#       ""size"":205739,""width"":1232,""height"":1085,
#   },
#
#   - "path" is the folder plus filename under "Signal\attachments.noindex"
#   - "fileName" is **not** unique, many messages have "image.png"
#   - so, instead, use the unique ID from "path" for "attachment.id"
#   - "url" field had folder and filename with "...Signal\drafts.noindex" but
#     for me those folders appeared empty, so ignoring this field completely
#   - saw cases where "fileName" wasn't present so put exception around each
#
# Returns:
#
#   - the number of attachments
#
# -----------------------------------------------------------------------------
def parse_attachments(attachments, the_message):

    count = 0

    if attachments:
        for attachment_json in attachments:

            attachment_x = attachment.Attachment()

            # need the attachment "id" and content type
            try:
                attachment_x.id = get_filename(attachment_json[JSON_ATTACHMENT_PATH])

                try:
                    attachment_x.type = attachment_json[JSON_ATTACHMENT_CONTENT_TYPE]
                except:
                    pass
                    
                try:
                    attachment_x.fileName = attachment_json[JSON_ATTACHMENT_FILENAME]
                except:
                    pass

                try:
                    attachment_x.size = attachment_json[JSON_ATTACHMENT_SIZE]
                except:
                    if the_config.debug:
                        error_str = the_config.get_str(the_config.STR_FAILED_TO_PARSE_ATTACHMENT_SIZE)
                        print(error_str + ' ' + e)
                    pass
                
                try:
                    attachment_x.width = attachment_json[JSON_ATTACHMENT_WIDTH]
                except Exception as e:
                    if the_config.debug:
                        error_str = the_config.get_str(the_config.STR_FAILED_TO_PARSE_ATTACHMENT_WIDTH)
                        print(error_str + ' ' + e)
                    pass

                try:
                    attachment_x.height = attachment_json[JSON_ATTACHMENT_HEIGHT]                    
                except Exception as e:
                    if the_config.debug:
                        error_str = the_config.get_str(the_config.STR_FAILED_TO_PARSE_ATTACHMENT_HEIGHT)
                        print(error_str + ' ' + e)
                    pass

            except Exception as e:
                if the_config.debug:
                    error_str = the_config.get_str(the_config.STR_FAILED_TO_PARSE_ATTACHMENT)
                    print(error_str + ' ' + e)
                pass

            if attachment_x.id and attachment_x.type:
                the_message.attachments.append(attachment_x)
                count += 1

    return count

# -----------------------------------------------------------------------------
#
# Parse the `json` portion of the message into a Reaction object and add to the 
# Message. Luckily, Signal stores reactions along with the original message.
#
# Parameters:
#
#   - reactions - actual reactions in JSON format
#   - the_message - the target Message object where the values will go
#
# Notes:
#
# - This is the format of the reactions
#
#   ""reactions"":[{
#       ""emoji"":""😮"", 
#       ""fromId"":""4320e55c-39db-4370-9a9e-2ffe1b7be661"", 
#       ""targetTimestamp"":1703540110922,  
#       ""timestamp"":1703543026900
#   }]
#
#  which is a collection of, you guessed it, reactions:
#   
#   - emoji - yes 🤣!
#   - fromId - the `conversation-id` associated with the person who reacted
#   - targetTimestamp - original message sent e.g. 2023-12-25 at 16:35
#   - timestamp - when they reacted e.g. at 22:23 on 2023-12-25
#
# Returns:
#
#   - number of reactions
#
# -----------------------------------------------------------------------------
def parse_reactions(reactions, the_message):

    count = 0

    the_config = config.Config()

    if reactions:
        for reaction_json in reactions:
            reaction = message.Reaction()
            reaction.emoji = reaction_json[JSON_EMOJI]
            reaction.timestamp = reaction_json[JSON_TIMESTAMP]
            reaction.target_time_sent = reaction_json[JSON_TARGET_TIMESTAMP]
            
            from_id = str(reaction_json[JSON_FROM_ID])
            reactor = person.Person()
            try:
                reactor = the_config.get_person_by_conversation_id(from_id)
            except Exception as e:
                print(e)

            if reactor:
                reaction.from_slug = reactor.slug
                the_message.reactions.append(reaction)

            count +=1

    return count

# -----------------------------------------------------------------------------
#
# If this is a reply, parse it.
#
# Parameters:
#
#   - data - the "quote" data
#   - the_message - where to put the reply
#
# Example:
#
#   ""quote"":{
#       ""id"":1661091484671,
#       ""authorUuid"":""db8ca91a-af41-4365-b498-b864117ce4bb"",
#       ""text"":""who is toby"",
#   }
#
# Where:
#
#   - id - the timestamp of the original message
#   - authorUuid - the unique ID of the person who sent the message
#   - text - the actual reply
#
# Notes:
# 
#   - The quoted reply is part of the JSON portion of the CSV row.
# 
# 
# -----------------------------------------------------------------------------
def parse_quote(data, the_message):

    try:
        the_message.quote.id = data[JSON_QUOTE_ID]
        the_message.quote.text = data[JSON_QUOTE_TEXT]
    except:
        pass

# -----------------------------------------------------------------------------
#
# Parse the `json` portion of the message into a Reaction object and adds the
# source service ID and attachment IDs.
#
# Parameters:
#
#   - row - the row from the CSV
#   - the_message - the target Message object where the values will go
#   - field_map - the mapping of colums to their field names
#
# Notes:
#
#   - The reactions are stored right inside the message row
#     or received (?) the message. 
#   - These are the key parts of the `json` 
#
#   {
#       ""timestamp"":1703540110922,
#       ""attachments"":[],
#       ""id"":""96b26f51-d1fe-4159-8721-57356f88d2ad"",
#       ""conversationId"":""a1760c87-d3d0-40f6-9992-ac0426efcc14"",
#       ""source"":""+12894005633"",
#       ""reactions"":[],
#       ""sourceServiceId"":""5965a5d4-7f37-4d48-8cdd-4c6ee99afe70""
#   }
#
#   where: 
#  
#   - `id` uniquely identifies the specific message
#   - `conversationId` uniquely identifies the conversation thread
#   - `sourceServiceId` uniquely identifies the person who sent
# 
# Returns:
#
#   - number of reactions + attachments
#
# -----------------------------------------------------------------------------
def parse_json(row, the_message, field_map):

    num_reactions = 0
    num_attachments = 0

    json_index = field_index(SIGNAL_JSON, field_map)
    data = row[json_index]

    try:
        json_data = json.loads(data)
    except Exception as e:
        print(the_message.id + ": " + e)

    try:
        the_message.source_service_id = json_data[JSON_SOURCE_SERVICE_ID]
    except:
        pass

    try:
        num_reactions = parse_reactions(json_data[JSON_REACTIONS], the_message)
    except:
        pass

    try:
        num_attachments = parse_attachments(json_data[JSON_ATTACHMENTS], the_message)
    except:
        pass
    
    try:
        parse_quote(json_data[JSON_QUOTE], the_message)
    except:
        pass

    return num_reactions + num_attachments

# -------------------------------------------------------------------------
#
# Lookup a person in the `Config.people` array by their Service ID.
#
# Parameters:
# 
#   - id - `serviceId` for the person
#
# Returns:
#
#   - False if no person found
#   - Person object if found 
#
# -------------------------------------------------------------------------
def get_person_by_service_id(id):

    the_config = config.Config()

    if len(id):
        for the_person in the_config.people:
            try:
                if the_person.service_id == id:
                    return the_person
            except Exception as e:
                print(e)
                pass
            
    return False

# -----------------------------------------------------------------------------
#
# Parse the date and time from a comma-separated row into the Message object.
#
# Parameters:
# 
#   - row - comma spearated data for the specific message
#   - message - the Message object where the data goes
#   - field_map - the mapping of colums to their field names
#
# Notes:
#
#   - example date/time `2023-06-11 15:33:58 UTC`
#
# -----------------------------------------------------------------------------
def parse_time(row, message, field_map):
    
    time_index = field_index(SIGNAL_SENT_AT, field_map)

    timestamp = int(row[time_index])
    time_in_seconds = int(timestamp/1000)

    # convert the time seconds since epoch to a time.struct_time object
    message.time = time.localtime(time_in_seconds)

    message.timestamp = time.mktime(message.time)
    message.set_date_time()

# -----------------------------------------------------------------------------
#
# Parse the People from a comma-separated row into a Message.
#
# Parameters:
# 
#   - row - comma spearated data for the specific message
#   - message - the Message object where the data goes
#   - field_map - the mapping of colums to their field names
#   - me - the Person object representing me
#
# Returns
#
#   - True - if a sender and receiver found
#   - False - if either is not found
#
# -----------------------------------------------------------------------------
def parse_people(row, message, field_map, me):

    the_config = config.Config()

    found = False

    message.id = row[field_index(SIGNAL_ID, field_map)]

    type = row[field_index(SIGNAL_TYPE, field_map)]

    if type not in [SIGNAL_INCOMING, SIGNAL_OUTGOING]:
        return found

    phone_index = field_index(SIGNAL_SOURCE, field_map)
    phone_number = row[phone_index]

    conversation_id_index = field_index(SIGNAL_CONVERSATION_ID, field_map)
    id = row[conversation_id_index]

    # see if it's a group message by checking the `conversation_id`
    group_slug = the_config.get_group_slug_by_conversation_id(id)
    if group_slug:
        message.group_slug = group_slug

    to_person = person.Person()

    # see who the message is to
    if type in [SIGNAL_INCOMING]:
        to_person = me

    elif not group_slug:
        
        # if it's a group slug then this call would generate an error since it
        # won't find the person and that could confuse the user
        try:
            to_person = the_config.get_person_by_conversation_id(id)
        except:
            pass

    # see who the message is from
    if type in [SIGNAL_OUTGOING]:
        from_person = me
    else:
        try:
            from_person = the_config.get_person_by_conversation_id(id)
        except:
            pass

        # if couldn't get them by the convo ID, it is likely a group so try the 
        # `sourceServiceId` which is inside the json portion
        if not from_person:
            service_id = message.source_service_id
            if service_id: 
                from_person = get_person_by_service_id(service_id)

    if from_person and len(from_person.slug):
        message.from_slug = from_person.slug

        # only need the from person (from_slug) because for group 
        # messages originating from me have me as "source"
        found = True

    if to_person and len(to_person.slug):
        message.to_slugs.append(to_person.slug)

    return found

# -----------------------------------------------------------------------------
#
# Parse one comma-separated row of the Signal `messages` CSV file into a 
# Message object.
#
# Parameters:
# 
#   - row - comma spearated data for the specific message
#   - message - the Message object where the data goes
#   - field_map - the mapping of colums to their field names
#
# Returns:
#
#   - True - if parsing was successful
#   - False - if not
# 
# -----------------------------------------------------------------------------
def parse_row(row, message, field_map):
   
    result = False

    the_config = config.Config()

    # see if it's incoming our outgoing
    type = row[field_index(SIGNAL_TYPE, field_map)]

    # only deal with "incoming" and "outgoing" messages
    if type in [SIGNAL_INCOMING, SIGNAL_OUTGOING]:

        body_index = field_index(SIGNAL_BODY, field_map)
        message.body = row[body_index]

        # parse the `json` portion of the message into a Reaction and
        # include it inside the Message object.
        try:
            parse_json(row, message, field_map)
        except:
            pass

    # find out who the people are in the conversation, i.e. who the
    # message is from and to 
    if parse_people(row, message, field_map, the_config.me):

        # we get here if we figured out who they are

        # add the message if there's a body or attachment(s)
        if len(message.body) or len(message.attachments):
            parse_time(row, message, field_map)
            result = True

    return result

# -----------------------------------------------------------------------------
#
# Load the messages from the CSV file
#
# Parameters:
# 
#   - filename - the CSV file
#   - messages - where the Message objects will go
#   - reactions - not used
#   - the_config - specific settings 
#
# Notes
#   - the first row is the header row, parse it in case the field order changes
#
# Returns: the number of messages
#
# -----------------------------------------------------------------------------
def load_messages(filename, messages, reactions, the_config):

    field_map = []

    with open(filename, 'r') as csv_file:
        reader = csv.reader(csv_file)

        count = 0
        for row in reader:
            if count == 0:
                parse_header(row, field_map)
            else:
                the_message = signal_message.SignalMessage()
                if parse_row(row, the_message, field_map):
                    messages.append(the_message)
            count += 1
    
    return count

# main

the_messages = []
the_reactions = [] 

the_config = config.Config()

if message_md.setup(the_config, markdown.YAML_SERVICE_SIGNAL):

    # load the conversation ID for each person
    conversations.parse_conversations_file(the_config)

    the_config.reversed = False

    # needs to be after setup so the command line parameters override the
    # values defined in the settings file
    message_md.get_markdown(the_config, load_messages, the_messages, the_reactions)