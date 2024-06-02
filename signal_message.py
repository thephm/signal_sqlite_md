# Signal messages have a `sourceServiceId` field that we need

import sys
sys.path.insert(1, '../message_md/')
import message

class SignalMessage(message.Message):
    def __init__(self):
        super(SignalMessage, self).__init__()

    source_service_id = ""