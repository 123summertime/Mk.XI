import asyncio
import json
from abc import ABC, abstractmethod
from typing import Literal, Optional, Union

from model import Config, MyProfile, Message, MkIXGetMessage, MkIXSystemMessage
from utils import MkIXMessageMemo, CQCode, Tools


class Event(ABC):
    _time: str
    _self_id: str
    _post_type: Literal["message", "notice", "request", "meta_event"]
    _message: Optional[Message]

    def __init__(self, message: Message, config: Config, self_id: str):
        self._message = message
        self._config = config
        self._self_id = self_id

    @abstractmethod
    def __call__(self) -> dict:
        raise NotImplementedError


class MessageEvent(Event):
    _post_type = "message"
    _message: MkIXGetMessage


class PrivateMessageEvent(MessageEvent):

    def __call__(self):
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

    def __call__(self):
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


class NoticeEvent(Event):
    _post_type = "notice"
    _message: Union[MkIXGetMessage, MkIXSystemMessage]


class GroupFileUpload(NoticeEvent):
    _message: MkIXGetMessage

    def __call__(self):
        return {
            "time": self._message.time,
            "self_id": self._self_id,
            "post_type": self._post_type,
            "notice_type": "group_upload",
            "group_id": self._message.group,
            "user_id": self._message.senderID,
            "file": {
                "id": self._message.payload.content,
                "name": self._message.payload.name,
                "size": self._message.payload.size,
            }
        }


class GroupBan(NoticeEvent):
    _message: MkIXGetMessage

    def __call__(self):
        return {
            "time": self._message.time,
            "self_id": self._self_id,
            "post_type": self._post_type,
            "notice_type": "group_ban",
            "sub_type": "lift_ban" if "解除" in self._message.payload.content[-6:] else "ban",
            "group_id": self._message.group,
            "user_id": self._message.senderID,
            "file": {
                "id": self._message.payload.content,
                "name": self._message.payload.name,
                "size": self._message.payload.size,
            }
        }


class FriendAdd(NoticeEvent):
    _message: MkIXSystemMessage

    def __call__(self):
        return {
            "time": self._message.time,
            "self_id": self._self_id,
            "post_type": self._post_type,
            "notice_type": "friend_add",
            "user_id": Tools.get_id_in_parentheses(self._message.payload)
        }


class GroupRecall(NoticeEvent):
    _message: MkIXGetMessage

    def __call__(self):
        return {
            "time": self._message.time,
            "self_id": self._self_id,
            "post_type": self._post_type,
            "notice_type": "group_recall",
            "group_id": self._message.group,
            "user_id": "0",  # not provide
            "operator_id": self._message.senderID,
            "message_id": self._message.payload.content,
        }


class FriendRecall(NoticeEvent):
    _message: MkIXGetMessage

    def __call__(self):
        return {
            "time": self._message.time,
            "self_id": self._self_id,
            "post_type": self._post_type,
            "notice_type": "friend_recall",
            "user_id": self._message.group,
            "message_id": self._message.payload.content,
        }


class RequestEvent(Event):
    _post_type = "request"
    _message: MkIXSystemMessage


class FriendRequest(RequestEvent):

    def __call__(self):
        return {
            "time": self._message.time,
            "self_id": self._self_id,
            "post_type": self._post_type,
            "request_type": "friend",
            "user_id": self._message.senderID,
            "comment": self._message.payload,
            "flag": self._message.time,
        }


class GroupRequest(RequestEvent):

    def __call__(self):
        return {
            "time": self._message.time,
            "self_id": self._self_id,
            "post_type": self._post_type,
            "request_type": "group",
            "sub_type": "add",
            "group_id": self._message.target,
            "user_id": self._message.senderID,
            "comment": self._message.payload,
            "flag": self._message.time,
        }


class MetaEvent(Event):
    _post_type = "meta_event"
    _message: None


class LifeCycle(MetaEvent):

    def __call__(self):
        return {
            "time": Tools.timestamp(),
            "self_id": self._self_id,
            "post_type": self._post_type,
            "meta_event_type": "lifecycle",
            "sub_type": "connect",
        }


class HeartBeat(MetaEvent):

    def __call__(self):
        return {
            "time": int(Tools.timestamp()),
            "self_id": self._self_id,
            "post_type": self._post_type,
            "meta_event_type": "heartbeat",
            "status": {

            },
            "interval": 30000,
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
    return event() if event else None
