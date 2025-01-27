import base64
import binascii
from abc import ABC, abstractmethod
from typing import Literal, Optional, Union, Awaitable

from Crypto.Cipher import AES
from Crypto.Util.Padding import unpad

from api import FetchAPI, Status
from model import Config, MyProfile, Message, MkIXGetMessage, MkIXSystemMessage
from utils import MkIXMessageMemo, CQCode, RequestMemo, Tools


class Event(ABC):
    _time: str
    _self_id: int
    _post_type: Literal["message", "notice", "request", "meta_event"]
    _message: Optional[Message]

    def __init__(self, message: Message, config: Config, self_id: str):
        self._message = message
        self._config = config
        self._self_id = self_id

    @abstractmethod
    async def __call__(self) -> Awaitable[Optional[dict]]:
        raise NotImplementedError


class MessageEvent(Event):
    _post_type = "message"
    _message: MkIXGetMessage

    def _decrypt(self) -> None:
        # 未加密
        if not self._message.payload.meta.get("encrypt", False):
            return
        # 加密但未设置密钥
        if self._message.group not in self._config.encrypt:
            raise RuntimeError

        key = self._config.encrypt[self._message.group].encode("utf-8")
        iv = binascii.unhexlify(self._message.payload.meta.get("iv", ""))
        try:
            data = base64.b64decode(self._message.payload.content)
            cipher = AES.new(key, AES.MODE_CBC, iv)
            decrypted = unpad(cipher.decrypt(data), AES.block_size)
            self._message.payload.content = decrypted.decode('utf-8')
            return
        except Exception:
            raise RuntimeError


class PrivateMessageEvent(MessageEvent):

    async def __call__(self):
        try:
            self._decrypt()
        except Exception:
            return None
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
        try:
            self._decrypt()
        except Exception:
            return None
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


class GroupAdmin(NoticeEvent):
    _message: MkIXSystemMessage

    async def __call__(self):
        return {
            "time": self._message.time,
            "self_id": self._self_id,
            "post_type": self._post_type,
            "notice_type": "group_admin",
            "sub_type": "set" if self._message.meta["operation"] == "group_admin_set" else "unset",
            "group_id": self._message.meta["var"]["id"],
            "user_id": self._self_id,
        }


class GroupDecrease(NoticeEvent):
    _message: MkIXGetMessage

    async def __call__(self):
        op = self._message.payload.meta["operation"]
        if op == "group_leave":
            tp = "leave"
        elif op == "group_kick":
            tp = "kick_me" if self._message.payload.meta["var"]["id"] == self._self_id else "kick"
        else:
            raise ValueError(f"Unknown operation type: {op}")

        return {
            "time": self._message.time,
            "self_id": self._self_id,
            "post_type": self._post_type,
            "notice_type": "group_decrease",
            "sub_type": tp,
            "group_id": self._message.group,
            "operator_id": self._message.payload.meta["var"]["operator"],
            "user_id": self._message.payload.meta["var"]["id"],
        }


class GroupIncrease(NoticeEvent):
    _message: MkIXGetMessage

    async def __call__(self):
        return {
            "time": self._message.time,
            "self_id": self._self_id,
            "post_type": self._post_type,
            "notice_type": "group_increase",
            "sub_type": "approve" if self._message.payload.meta["var"]["way"] == "request" else "invite",
            "group_id": self._message.group,
            "operator_id": self._message.payload.meta["var"]["operator"],
            "user_id": self._message.payload.meta["var"]["id"],
        }


class GroupBan(NoticeEvent):
    _message: MkIXGetMessage

    async def __call__(self):
        return {
            "time": self._message.time,
            "self_id": self._self_id,
            "post_type": self._post_type,
            "notice_type": "group_ban",
            "sub_type": "ban" if self._message.payload.meta["operation"] == "group_ban" else "lift_ban",
            "group_id": self._message.group,
            "operator_id": self._message.payload.meta["var"]["operator"],
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
            "user_id": self._message.meta["var"]["id"],
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
            "user_id": self._message.payload.meta["var"]["sender"],
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

    def __init__(self, self_id: str):
        self._self_id = self_id


class LifeCycle(MetaEvent):

    async def __call__(self):
        return {
            "time": int(Tools.timestamp()),
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
            "self_id": int(self._self_id),
            "post_type": self._post_type,
            "meta_event_type": "heartbeat",
            "status": status,
            "interval": 30000,
        }


async def event_mapping(message: dict,
                        launch_time: str,
                        config: Config,
                        profile: MyProfile) -> Awaitable[Optional[dict]]:
    Tools.logger().info(f'Receive MkIX message: {message}')
    memo = MkIXMessageMemo.get_instance()

    def handle_system_message(model: MkIXSystemMessage):
        if model.type == "echo":
            memo.receive_echo(model)
            return None
        if model.type == "notice":
            op = model.meta["operation"]
            if op in ("friend_request_accepted"):
                profile.friends.add(model.meta["var"]["id"])
                return FriendAdd
            if op in ("group_admin_set", "group_admin_unset"):
                return GroupAdmin
            return None
        req_memo = RequestMemo.get_instance()
        if model.type == "join" and model.state == "等待审核":
            req_memo.put(model)
            return GroupRequest
        if model.type == "friend" and model.state == "等待审核":
            req_memo.put(model)
            return FriendRequest
        return None

    def handle_group_message(model: MkIXGetMessage):
        if model.type == "system":
            op = model.payload.meta["operation"]
            if op in ("group_joined"):
                if model.meta["var"]["id"] == profile.uuid:
                    profile.groups.add(model.group)
                return GroupIncrease
            if op in ("group_ban", "group_lift_ban"):
                return GroupBan
            if op in ("group_kick", "group_leave"):
                return GroupDecrease
            return None
        if model.type == "file":
            return GroupFileUpload
        if model.type == "revoke":
            return GroupRecall
        memo.receive_chat(model, "group")
        return GroupMessageEvent

    def handle_private_message(model: MkIXGetMessage):
        if model.type == "system":
            return None
        if model.type == "file":
            return GroupFileUpload
        if model.type == "revoke":
            return FriendRecall
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
        if model.time < launch_time or model.senderID == profile.uuid:
            return None

    return (await event(model, config, profile.uuid)()) if event else None
