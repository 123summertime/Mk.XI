from abc import ABC, abstractmethod
from typing import Literal, Optional, Union, Awaitable

from model import Config, MyProfile, Message, MkIXGetMessage, MkIXSystemMessage
from utils import MkIXMessageMemo, CQCode, Tools
from api import FetchAPI, Status


class Event(ABC):
    _time: str
    _self_id: int
    _post_type: Literal["message", "notice", "request", "meta_event"]
    _message: Optional[Message]

    def __init__(self, message: Message, config: Config, self_id: int):
        self._message = message
        self._config = config
        self._self_id = self_id

    @abstractmethod
    async def __call__(self) -> Awaitable[dict]:
        raise NotImplementedError


class MessageEvent(Event):
    _post_type = "message"
    _message: MkIXGetMessage


class PrivateMessageEvent(MessageEvent):

    async def __call__(self):
        return {
            "time": self._message.time,
            "self_id": self._self_id,
            "post_type": self._post_type,
            "message_type": "private",
            "sub_type": "friend",
            "message_id": self._message.time,
            "user_id": self._message.senderID,
            "message": CQCode.serialization(self._message, self._config, "array", "private"),
            "raw_message": CQCode.serialization(self._message, self._config, "string", "private"),
            "message_format": "array",
            "font": -1,
            "sender": {
                "user_id": self._message.senderID,
            }
        }


class GroupMessageEvent(MessageEvent):

    async def __call__(self):
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
            "message": CQCode.serialization(self._message, self._config, "array", "group"),
            "raw_message": CQCode.serialization(self._message, self._config, "string", "group"),
            "message_format": "array",
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

    async def __call__(self):
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
                "busid": 0,
            }
        }


class GroupBan(NoticeEvent):
    _message: MkIXGetMessage

    async def __call__(self):
        return {
            "time": self._message.time,
            "self_id": self._self_id,
            "post_type": self._post_type,
            "notice_type": "group_ban",
            "sub_type": "lift_ban" if "解除" in self._message.payload.content[-6:] else "ban",
            "group_id": self._message.group,
            "operator_id": 0,  # not provide
            "user_id": self._message.payload.meta["var"]["id"],
            "duration": self._message.payload.meta["var"]["duration"],
        }


class FriendAdd(NoticeEvent):
    _message: MkIXSystemMessage

    async def __call__(self):
        return {
            "time": self._message.time,
            "self_id": self._self_id,
            "post_type": self._post_type,
            "notice_type": "friend_add",
            "user_id": 0,   # not provide
        }


class GroupRecall(NoticeEvent):
    _message: MkIXGetMessage

    async def __call__(self):
        return {
            "time": self._message.time,
            "self_id": self._self_id,
            "post_type": self._post_type,
            "notice_type": "group_recall",
            "group_id": self._message.group,
            "user_id": 0,  # not provide
            "operator_id": self._message.senderID,
            "message_id": self._message.payload.meta["var"]["time"],
        }


class FriendRecall(NoticeEvent):
    _message: MkIXGetMessage

    async def __call__(self):
        return {
            "time": self._message.time,
            "self_id": self._self_id,
            "post_type": self._post_type,
            "notice_type": "friend_recall",
            "user_id": self._message.group,
            "message_id": self._message.payload.meta["var"]["time"],
        }


class RequestEvent(Event):
    _post_type = "request"
    _message: MkIXSystemMessage


class FriendRequest(RequestEvent):

    async def __call__(self):
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

    async def __call__(self):
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

    async def __call__(self):
        return {
            "time": Tools.timestamp(),
            "self_id": self._self_id,
            "post_type": self._post_type,
            "meta_event_type": "lifecycle",
            "sub_type": "connect",
        }


class HeartBeat(MetaEvent):

    async def __call__(self):
        status = await FetchAPI.get_instance().call(Status)
        return {
            "time": int(Tools.timestamp()),
            "self_id": self._self_id,
            "post_type": self._post_type,
            "meta_event_type": "heartbeat",
            "status": status,
            "interval": 30000,
        }


async def event_mapping(message: dict,
                        launch_time: str,
                        config: Config,
                        profile: MyProfile) -> Awaitable[Optional[dict]]:
    print('Receive MkIX message', message["type"])
    if message["time"] < launch_time:
        return None

    memo = MkIXMessageMemo.get_instance()

    def handle_system_message(model: MkIXSystemMessage):
        if model.type == "echo":
            memo.receive_echo(model)
            return None
        if model.type == "notice" and model.payload.endswith("已通过你的好友申请"):
            return FriendAdd
        mapping = {
            "join": GroupRequest,
            "friend": FriendRequest,
        }
        return mapping.get(model.type, None)

    def handle_group_message(model: MkIXGetMessage):
        if model.type == "system":
            content = model.payload.content
            if '禁言' in content and (content.endswith('分钟') or content.endswith('禁言')):
                return GroupBan
            return None
        mapping = {
            "file": GroupFileUpload,
            "revoke": GroupRecall
        }
        if model.type in mapping:
            return mapping[model.type]
        memo.receive_chat(model, "group")
        return GroupMessageEvent

    def handle_private_message(model: MkIXGetMessage):
        private_event_map = {
            "revoke": FriendRecall
        }
        if model.type in private_event_map:
            return private_event_map[model.type]
        memo.receive_chat(model, "friend")
        return PrivateMessageEvent

    if message["isSystemMessage"]:
        model = MkIXSystemMessage.model_validate(message)
        event = handle_system_message(model)
    else:
        model = MkIXGetMessage.model_validate(message)
        if model.group in profile.groups:
            event = handle_group_message(model)
        else:
            event = handle_private_message(model)

    return (await event(model, config, int(profile.uuid))()) if event else None
