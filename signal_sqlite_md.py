import csv
import time
import json
from datetime import datetime, timezone
import tzlocal # pip install tzlocal

import sys
import conversations
import attachments
import signal_message
sys.path.insert(1, '../hal/')
import person
sys.path.insert(1, '../message_md/')
import message_md
import config
import markdown
import message

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

SIGNAL_SOURCE_SERVICE_ID = "sourceServiceId"  # Service ID of the sender/recipient 

JSON_REACTIONS = "reactions"
JSON_TIMESTAMP = "timestamp"
JSON_FROM_ID = "fromId"
JSON_EMOJI = "emoji"
JSON_TARGET_TIMESTAMP = "targetTimestamp"
JSON_QUOTE = "quote"
JSON_QUOTE_ID = "id"
JSON_QUOTE_TEXT = "text"

SignalFields = [
    SIGNAL_ROW_ID, SIGNAL_ID, SIGNAL_JSON, SIGNAL_SENT_AT, 
    SIGNAL_CONVERSATION_ID, SIGNAL_SOURCE, SIGNAL_HAS_ATTACHMENTS, 
    SIGNAL_TYPE, SIGNAL_BODY, SIGNAL_SOURCE_SERVICE_ID
]

def parse_header(row, field_map):
    """
    Parse the header row of the `messages.csv` file and map it to the fields.
    
    Parameters:
    row (list): The header row from the CSV file containing column names.
    field_map (list): The field names and their indices will be stored.

    Returns:
    dict: Dictionary mapping field names to their column indices.
          Example: {'timestamp': 0, 'sender': 1, 'message': 2}
    """

    global SignalFields

    count = 0
    for col in row:
        for field in SignalFields:
            if col == field:
                field_map.append([field, count])
        count += 1

def field_index(field_label, field_map):
    """
    Find the index of a specific field in the `field_map` based on its label.

    Parameters:
    field_label (str): Label of the field to find e.g., ATTACHMENT_CONTENT_TYPE
    field_map (list): List mapping field names to their indices in the CSV row.

    Returns:
    int: The index of the field if found, otherwise -1.
    """

    result = -1

    for field in field_map:
        if field[0] == field_label:
            result = field[1]
            break

    return result

def get_filename(str):
    """
    Extract the filename from a given string by finding the last occurrence of "\\".
    
    Parameters:
    str (str): The input string from which to extract the filename.
    
    Returns:
    str: The filename extracted from the string, or the original string if "\\" is not found.

    Example:
    - `"path":"97\\977e7e5f43d0c935ad785b290023d1455631351772b2f8c53e5ced4a5f8ffb81"`
    - returns: `977e7e5f43d0c935ad785b290023d1455631351772b2f8c53e5ced4a5f8ffb81`
    """

    index = str.rfind("\\")
    
    if index != -1:
        result = str[index + 1:]
        return result
    else:
        # if "\\" is not found, return the original string
        return str

def parse_reactions(reactions, the_message):
    """
    Parse the `json` portion of the message into a Reaction object and add to the 
    Message. Luckily, Signal stores reactions along with the original message.
    
    Parameters:
    reactions (list): List of reaction data in JSON format.
    the_message (Message): The Message object where the reactions will be added.
    
    Returns:
    int: The number of reactions added to the Message object.

    # Notes:

    - This is the format of the reactions

    ""reactions"":[{
    ""emoji"":""😮"", 
    ""fromId"":""4320e55c-39db-4370-9a9e-2ffe1b7be661"", 
    ""targetTimestamp"":1703540110922,  
    ""timestamp"":1703543026900
    }]

    which is a collection of, you guessed it, reactions:

    - emoji - yes 🤣!
    - fromId - the `conversation-id` associated with the person who reacted
    - targetTimestamp - original message sent e.g. 2023-12-25 at 16:35
    - timestamp - when they reacted e.g. at 22:23 on 2023-12-25
    """

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

def parse_quote(data, the_message):
    """
    If this is a reply, parse the "quote" data from the JSON portion of the 
    message and set it in the Message object.
    
    Parameters:
    data (dict): The "quote" data from the JSON portion of the message.
    the_message (Message): The Message object where the quote data will be set.

    Example:

    ""quote"":{
        ""id"":1661091484671,
        ""authorUuid"":""db8ca91a-af41-4365-b498-b864117ce4bb"",
        ""text"":""who is toby"",
    }
    where:
    - id - the timestamp of the original message
    - authorUuid - the unique ID of the person who sent the message
    - text - the actual reply

    Notes:
    - The quoted reply is part of the JSON portion of the CSV row.
    """

    try:
        the_message.quote.id = data[JSON_QUOTE_ID]
        the_message.quote.text = data[JSON_QUOTE_TEXT]
    except:
        pass

def parse_json(row, the_message, field_map):
    """
    Parse the `json` portion of the message into a Reaction object and adds the
    source service ID and attachment IDs.
    
    Parameters:
    row (list): The row from the CSV file containing the message data.
    the_message (Message): The target Message object where the values will be set.
    field_map (dict): The mapping of columns to their field names.

    Notes:
    - The reactions are stored right inside the message row
    or received (?) the message.
    - The `json` portion of the message contains various fields including:
    {
        "timestamp": 1703540110922,
        "attachments": [],
        "id": "96b26f51-d1fe-4159-8721-57356f88d2ad",
        "conversationId": "a1760c87-d3d0-40f6-9992-ac0426efcc14",
        "source": "+12894005633",
        "reactions": [],
        "sourceServiceId": "5965a5d4-7f37-4d48-8cdd-4c6ee99afe70"
    }
    where:
    - `id` uniquely identifies the specific message
    - `conversationId` uniquely identifies the conversation thread
    - `sourceServiceId` uniquely identifies the person who sent the message

    Returns:
    int: The number of reactions and attachments parsed from the message.
    """

    num_reactions = 0
    num_attachments = 0
    
    json_index = field_index(SIGNAL_JSON, field_map)
    data = row[json_index]

    try:
        json_data = json.loads(data)
    except Exception as e:
        print("Error parsing JSON for message " + the_message.id + ": " + e)

    try:
        num_reactions = parse_reactions(json_data[JSON_REACTIONS], the_message)
    except:
        pass

    try:
        parse_quote(json_data[JSON_QUOTE], the_message)
    except:
        pass

    return num_reactions + num_attachments

def get_person_by_service_id(id):
    """
    Lookup a person in the `Config.people` array by their Service ID.

    Parameters:
    id (int): The `serviceId` for the person to look up.

    Returns:
    bool: False if no person found 
    Person: Person object if a person was found
    """

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

def parse_time(row, message, field_map):
    """
    Parse the date and time from a comma-separated row into the Message object.
    
    Parameters:
    row (list): The row from the CSV file containing the message data.
    message (Message): The Message object where the date and time will be set.
    field_map (dict): The mapping of columns to their field names.

    Notes:
    - The `sent_at` field in the CSV is a timestamp in milliseconds since epoch.
    - The timestamp is converted to seconds by dividing by 1000.
    - The time is then converted to a `time.struct_time` object.
    """
    
    time_index = field_index(SIGNAL_SENT_AT, field_map)

    timestamp = int(row[time_index])
    time_in_seconds = int(timestamp/1000)

    # convert the time seconds since epoch to a time.struct_time object
    message.time = time.localtime(time_in_seconds)

    message.timestamp = time.mktime(message.time)
    message.set_date_time()

def parse_people(row, message, field_map, me):
    """
    Parse the People from a comma-separated row into a Message.

    Parameters:
    row (list): The row from the CSV file containing the message data.
    message (Message): The Message object where the data will be set.
    field_map (dict): The mapping of columns to their field names.
    me (Person): The Person object representing the user (me).

    Returns:
    bool: True if sender and receiver found. False if neither is found.
    """

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

    from_person = False
    
    # see who the message is from
    if type in [SIGNAL_OUTGOING]:
        from_person = me
    else:
        # it's an incoming message
        service_id = message.source_service_id

        # if couldn't get them by the convo ID, it is likely a group so try the 
        # `sourceServiceId` which is inside the json portion
        if not from_person and service_id:
            from_person = get_person_by_service_id(service_id)

    if from_person and len(from_person.slug):
        message.from_slug = from_person.slug

        # only need the from person (from_slug) because for group 
        # messages originating from me have me as "source"
        found = True

    if to_person and len(to_person.slug):
        message.to_slugs.append(to_person.slug)

    return found

def parse_row(row, message, field_map):
    """
    Parse one comma-separated row of the Signal `messages` CSV file into a
    Message object.

    Parameters:
    row (list): The row from the CSV file containing the message data.
    message (Message): The Message object where the data will be set.
    field_map (dict): The mapping of columns to their field names.

    Returns:
    bool: True if parsing was successful, False otherwise.
    """
   
    result = False

    the_config = config.Config()

    # see if it's incoming our outgoing

    type = row[field_index(SIGNAL_TYPE, field_map)]

    # only deal with "incoming" and "outgoing" messages
    if type in [SIGNAL_INCOMING, SIGNAL_OUTGOING]:

        body_index = field_index(SIGNAL_BODY, field_map)
        message.body = row[body_index]

        message.has_attachments = field_index(SIGNAL_HAS_ATTACHMENTS, field_map)

        try:
            service_id_index = field_index(SIGNAL_SOURCE_SERVICE_ID, field_map)
            message.source_service_id = row[service_id_index]
        except:
            pass

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

        parse_time(row, message, field_map)

        if len(message.body) or message.has_attachments:
            result = True

    return result

def load_messages(filename, messages, reactions, the_config):
    """
    Load the Signal messages from the CSV file and parse into Message objects.

    Parameters:
    filename (str): The path to the CSV file containing the messages.
    messages (list): The list where the parsed Message objects will be stored.
    reactions (array): Not used in this function.
    the_config (Config): The configuration object containing settings and metadata.

    Returns:
    int: The number of messages parsed from the CSV file.
    """

    field_map = []

    with open(filename, 'r') as csv_file:
        reader = csv.reader(csv_file)

        count = 0
        for row in reader:
            if count == 0:
                parse_header(row, field_map)
                # [['rowid', 0], ['id', 1], ['json', 2], ['sent_at', 5], ['conversationId', 7], ['source', 9], ['hasAttachments', 10], ['type', 15], ['body', 16]]
            else:
                the_message = signal_message.SignalMessage()
                if parse_row(row, the_message, field_map):
                    messages.append(the_message)
            count += 1

    # Load the metadata from attachments export
    attachments.parse_attachments_file(messages, the_config)

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