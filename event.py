import asyncio
import json
from abc import ABC, abstractmethod
from typing import Literal, Optional

from model import Config, MyProfile, Message, MkIXGetMessage, MkIXSystemMessage
from utils import MkIXMessageMemo, CQCode


class Event(ABC):
    _time: str
    _self_id: str
    _post_type: Literal["message", "notice", "request", "meta_event"]
    _message: Message

    def __init__(self, message: Message, config: Config, self_id: str):
        self._message = message
        self._config = config
        self._self_id = self_id

    @abstractmethod
    def build(self) -> dict:
        raise NotImplementedError


class MessageEvent(Event):
    _post_type = "message"
    _message: MkIXGetMessage


class PrivateMessageEvent(MessageEvent):

    def build(self):
        return {
            "time": self._message.time,
            "self_id": self._self_id,
            "post_type": self._post_type,
            "message_type": "private",
            "sub_type": "friend",
            "message_id": self._message.time,
            "group_id": self._message.group,
            "user_id": self._message.senderID,
            "message": CQCode.serialization(self._message, self._config, "private"),
            "raw_message": CQCode.serialization(self._message, self._config, "private"),
            "message_format": "string",
            "font": -1,
            "sender": {
                "user_id": self._message.senderID,
            }
        }


class GroupMessageEvent(MessageEvent):

    def build(self):
        return {
            "time": self._message.time,
            "self_id": self._self_id,
            "post_type": self._post_type,
            "message_type": "group",
            "sub_type": "normal",
            "message_id": self._message.time,
            "group_id": self._message.group,
            "user_id": self._message.senderID,
            "anonymous": None,
            "message": CQCode.serialization(self._message, self._config, "group"),
            "raw_message": CQCode.serialization(self._message, self._config, "group"),
            "message_format": "string",
            "font": -1,
            "sender": {
                "user_id": self._message.senderID,
            }
        }


def event_mapping(message: dict, launch_time: str, config: Config, profile: MyProfile) -> Optional[Event]:
    print('Receive MkIX message', message["type"])

    if message["time"] < launch_time:
        return None

    event = None
    memo = MkIXMessageMemo.get_instance()

    if message["isSystemMessage"]:
        model = MkIXSystemMessage.model_validate(message)
        if model.type == "echo":
            memo.receive_echo(model)
    else:
        model = MkIXGetMessage.model_validate(message)
        if model.group in profile.groups:
            memo.receive_chat(model, "group")
            event = GroupMessageEvent(model, config, profile.uuid)
        else:
            memo.receive_chat(model, "friend")
            event = PrivateMessageEvent(model, config, profile.uuid)
    return event.build() if event else None
