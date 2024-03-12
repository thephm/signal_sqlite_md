import csv
import time
import json
from datetime import datetime, timezone
import tzlocal # pip install tzlocal

import sys
import conversations
sys.path.insert(1, '../message_md/')
import message_md
import config
import markdown
import message
import person
import attachment

SIGNAL_ROW_ID = "rowid"
SIGNAL_ID = "id"
SIGNAL_JSON = "json"
SIGNAL_SENT_AT = "sent_at"
SIGNAL_CONVERSATION_ID = "conversationId"
SIGNAL_SOURCE = "source"
SIGNAL_HAS_ATTACHMENTS = "hasAttachments"
SIGNAL_TYPE = "type"
SIGNAL_BODY = "body"

SIGNAL_INCOMING = "incoming"
SIGNAL_OUTGOING = "outgoing"

JSON_REACTIONS = "reactions"
JSON_ATTACHMENTS = "attachments"
JSON_TIMESTAMP = "timestamp"
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

# -----------------------------------------------------------------------------
#
# Parse the header row of the `messages.csv` file and map it to the fields
#
# Parameters:
#
#   - row - the header row
#   - fieldMap - where the result goes
#
# -----------------------------------------------------------------------------
def parseHeader(row, fieldMap):

    global SignalFields

    count = 0
    for col in row:
        for field in SignalFields:
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
# Get the filename from "path" attribute in "attachments"
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
def getFileName(str):
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
#   - theMessage - the target Message object where the values will go
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
def parseAttachments(attachments, theMessage):

    count = 0

    if attachments:
        for attachmentJSON in attachments:

            attachmentX = attachment.Attachment()

            # need the attachment "id" and content type
            try:
                attachmentX.id = getFileName(attachmentJSON[JSON_ATTACHMENT_PATH])

                try:
                    attachmentX.type = attachmentJSON[JSON_ATTACHMENT_CONTENT_TYPE]
                except:
                    pass
                    
                try:
                    attachmentX.fileName = attachmentJSON[JSON_ATTACHMENT_FILENAME]
                except:
                    pass

                try:
                    attachmentX.size = attachmentJSON[JSON_ATTACHMENT_SIZE]
                except:
                    if theConfig.debug:
                        print("Failed to parse attachment additional info. " + e)
                    pass
                
                try:
                    attachmentX.width = attachmentJSON[JSON_ATTACHMENT_WIDTH]
                except Exception as e:
                    if theConfig.debug:
                        print("Failed to parse attachment additional info. " + e)
                    pass

                try:
                    attachmentX.height = attachmentJSON[JSON_ATTACHMENT_HEIGHT]                    
                except Exception as e:
                    if theConfig.debug:
                        print("Failed to parse attachment additional info. " + e)
                    pass

            except Exception as e:
                if theConfig.debug:
                    print("Failed to parse attachment. " + e)
                pass

            if attachmentX.id and attachmentX.type:
                theMessage.attachments.append(attachmentX)
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
#   - theMessage - the target Message object where the values will go
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
def parseReactions(reactions, theMessage):

    count = 0

    theConfig = config.Config()

    if reactions:
        for reactionJSON in reactions:
            reaction = message.Reaction()
            reaction.emoji = reactionJSON[JSON_EMOJI]
            reaction.timestamp = reactionJSON[JSON_TIMESTAMP]
            reaction.targetTimeSent = reactionJSON[JSON_TARGET_TIMESTAMP]
            
            fromId = str(reactionJSON[JSON_FROM_ID])
            reactor = person.Person()
            try:
                reactor = theConfig.getPersonByConversationId( fromId )
            except Exception as e:
                print(e)

            if reactor:
                reaction.fromSlug = reactor.slug
                theMessage.reactions.append(reaction)

            count +=1

    return count

# -----------------------------------------------------------------------------
#
# If this is a reply, process it
#
# The quoted reply is part of the JSON portion of the CSV row.
#
# Parameters:
#
#   - data - the "quote" data
#   - theMessage - where to put the reply
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
# -----------------------------------------------------------------------------
def parseQuote(data, theMessage):

    try:
        theMessage.quote.id = data[JSON_QUOTE_ID]
        theMessage.quote.text = data[JSON_QUOTE_TEXT]
    except:
        pass

# -----------------------------------------------------------------------------
#
# Parse the `json` portion of the message into a Reaction object. Luckily, they
# store the reactions right in the message row.
#
# Parameters:
#
#   - row - the row from the CSV
#   - theMessage - the target Message object where the values will go
#   - fieldMap - the mapping of colums to their field names
#
# Notes:
#
# - These are the key parts of the `json` 
#
#   {
#       ""timestamp"":1703540110922,
#       ""attachments"":[],
#       ""id"":""96b26f51-d1fe-4159-8721-57356f88d2ad"",
#       ""conversationId"":""a1760c87-d3d0-40f6-9992-ac0426efcc14"",
#       ""source"":""+12894005633"",
#       ""reactions"":[]
#   }
#
# Returns:
#
#   - number of reactions + attachments
#
# -----------------------------------------------------------------------------
def parseJSON(row, theMessage, fieldMap):

    numReactions = 0
    numAttachments = 0

    jsonIndex = fieldIndex(SIGNAL_JSON, fieldMap)
    data = row[jsonIndex]

    try:
        jsonData = json.loads(data)
    except Exception as e:
        print(theMessage.id + ": " + e)

    try:
        numReactions = parseReactions(jsonData[JSON_REACTIONS], theMessage)
    except:
        pass

    try:
        numAttachments = parseAttachments(jsonData[JSON_ATTACHMENTS], theMessage)
    except:
        pass

    
    try:
        parseQuote(jsonData[JSON_QUOTE], theMessage)
    except:
        pass

    return numReactions + numAttachments

# -----------------------------------------------------------------------------
#
# Parse the date and time from a comma-separated row into a Message
#
# Parameters:
# 
#   - row - comma spearated data for the specific message
#   - message - the Message object where the data goes
#   - fieldMap - the mapping of colums to their field names
#
# Notes:
#
#   - example date/time `2023-06-11 15:33:58 UTC`
#
# -----------------------------------------------------------------------------
def parseTime(row, message, fieldMap):
    
    timeIndex = fieldIndex(SIGNAL_SENT_AT, fieldMap)

    timestamp = int(row[timeIndex])
    timeInSeconds = int(timestamp/1000)

    # convert the time seconds since epoch to a time.struct_time object
    message.time = time.localtime(timeInSeconds)

    message.timeStamp = time.mktime(message.time)
    message.setDateTime()

# -----------------------------------------------------------------------------
#
# Parse the People from a comma-separated row into a Message
#
# Parameters:
# 
#   - row - comma spearated data for the specific message
#   - message - the Message object where the data goes
#   - fieldMap - the mapping of colums to their field names
#   - me - the Person object representing me
#
# Returns
#
#   - True - if a sender and receiver found
#   - False - if either is not found
#
# -----------------------------------------------------------------------------
def parsePeople(row, message, fieldMap, me):

    theConfig = config.Config()

    found = False

    typeIndex = fieldIndex(SIGNAL_TYPE, fieldMap)
    type = row[typeIndex]

    if type not in [SIGNAL_INCOMING, SIGNAL_OUTGOING]:
        return found

    phoneIndex = fieldIndex(SIGNAL_SOURCE, fieldMap)
    phoneNumber = row[phoneIndex]

    conversationIdIndex = fieldIndex(SIGNAL_CONVERSATION_ID, fieldMap)
    id = row[conversationIdIndex]

    # see if it's a group message by checking the `conversation_id`
    groupSlug = theConfig.getGroupSlugByConversationId(id)
    if groupSlug:
        message.groupSlug = groupSlug

    toPerson = person.Person()

    if type in [SIGNAL_INCOMING]:
        toPerson = me
    elif not groupSlug:
        # if it's a group slug then this call would generate an 
        # error since it won't find the person and that could 
        # confuse the user
        toPerson = theConfig.getPersonByConversationId(id)

    if type in [SIGNAL_OUTGOING]:
        fromPerson = me
    else:
        fromPerson = theConfig.getPersonByNumber(phoneNumber)
 
    if fromPerson and len(fromPerson.slug):
        message.fromSlug = fromPerson.slug

        # only need the from person (fromSlug) because for group 
        # messages originating from me have me as "source"
        found = True

        if toPerson and len(toPerson.slug):
            message.toSlugs.append(toPerson.slug)

    messageIdIndex = fieldIndex(SIGNAL_ID, fieldMap)
    message.id = row[messageIdIndex]

    return found

# -----------------------------------------------------------------------------
#
# Parse one comma-separated row into a Message object
#
# Parameters:
# 
#   - row - comma spearated data for the specific message
#   - message - the Message object where the data goes
#   - fieldMap - the mapping of colums to their field names
#
# Returns:
#
#   - True - if parsing was successful
#   - False - if not
# 
# -----------------------------------------------------------------------------
def parseRow(row, message, fieldMap):
   
    result = False

    theConfig = config.Config()

    if parsePeople(row, message, fieldMap, theConfig.me):

        typeIndex = fieldIndex(SIGNAL_TYPE, fieldMap)
        type = row[typeIndex]

        if type in [SIGNAL_INCOMING, SIGNAL_OUTGOING]:

            bodyIndex = fieldIndex(SIGNAL_BODY, fieldMap)
            body = row[bodyIndex]
            
            message.body = body

            try:
                parseJSON(row, message, fieldMap)
            except:
                pass

            # add the message if there's a body or attachment(s)
            if len(body) or len(message.attachments):
                parseTime(row, message, fieldMap)
                result = True

    return result

# -----------------------------------------------------------------------------
#
# Load the messages from the CSV file
#
# Parameters:
# 
#   - fileName - the CSV file
#   - messages - where the Message objects will go
#   - reactions - not used
#   - theConfig - specific settings 
#
# Notes
#   - the first row is the header row, parse it in case the field order changes
#
# Returns: the number of messages
#
# -----------------------------------------------------------------------------
def loadMessages(fileName, messages, reactions, theConfig):

    fieldMap = []

    with open(fileName, 'r') as csv_file:
        reader = csv.reader(csv_file)

        count = 0
        for row in reader:
            if count == 0:
                parseHeader(row, fieldMap)
            else:
                theMessage = message.Message()
                if parseRow(row, theMessage, fieldMap):
                    messages.append(theMessage)
            count += 1
    
    return count


# main

theMessages = []
theReactions = [] 

theConfig = config.Config()

if message_md.setup(theConfig, markdown.YAML_SERVICE_SIGNAL, True):

    # load the conversation ID for each person
    conversations.parseConversationsFile(theConfig)

    theConfig.reversed = False

    # needs to be after setup so the command line parameters override the
    # values defined in the settings file
    message_md.getMarkdown(theConfig, loadMessages, theMessages, theReactions)