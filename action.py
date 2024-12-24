from abc import ABC, abstractmethod
from model import OB11ActionData, MkIXPostMessage, CQDataListItem, CQData, MkIXMessagePayload
from utils import CQCode
from typing import Union, Literal, Optional
from utils import MkIXMessageMemo
from api import GroupKick, GroupBan


class MessageAction:

    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, '_' + k, v)
        if isinstance(self._message, list):
            self._message = [CQDataListItem.model_validate(i) for i in self._message]
        else:
            self._message = CQData(data=self._message)

    def __call__(self) -> list[MkIXPostMessage]:
        model_list = CQCode.deserialization(self._message)
        self._add_info(model_list)
        return model_list

    def _add_info(self, model_list: list[MkIXPostMessage]) -> None:
        """ 增加额外的信息，原地修改 """
        pass


class SendPrivateMsg(MessageAction):
    _user_id: str
    _message: Union[str, list]
    _auto_escape = False

    def _add_info(self, model_list: list[MkIXPostMessage]) -> None:
        for i in model_list:
            i.group = str(self._user_id)
            i.groupType = "friend"


class SendGroupMsg(MessageAction):
    _group_id: str
    _message: Union[str, list]
    _auto_escape = False

    def _add_info(self, model_list: list[MkIXPostMessage]) -> None:
        for i in model_list:
            i.group = str(self._group_id)
            i.groupType = "group"


class SendMsg(MessageAction):
    _message_type: Optional[Literal["group", "private"]] = None
    _user_id: Optional[str] = None
    _group_id: Optional[str] = None
    _message: Union[str, list]
    _auto_escape = False

    def _add_info(self, model_list: list[MkIXPostMessage]) -> None:
        group_type = ""
        if self._message_type:
            if self._message_type == "group":
                group_type = "group"
            elif self._message_type == "private":
                group_type = "friend"
        else:
            if self._group_id:
                group_type = "group"
            elif self._user_id:
                group_type = "friend"
        group_id = str(self._group_id if group_type == "group" else self._user_id)

        for i in model_list:
            i.groupType = group_type
            i.group = group_id


class Action(ABC):

    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, '_' + k, v)

    @abstractmethod
    def __call__(self):
        raise NotImplementedError


class DeleteMsg(Action):
    _message_id: str

    def __call__(self) -> list[MkIXPostMessage]:
        memo = MkIXMessageMemo.get_instance()
        group_type, group_id, revoke_messages = memo.get_storage(self._message_id)
        model_list = []
        for i in revoke_messages:
            model = MkIXPostMessage(
                type="revokeRequest",
                group=group_id,
                groupType="private" if group_type == "friend" else "group",
                payload=MkIXMessagePayload(
                    content=i,
                )
            )
            model_list.append(model)
        return model_list


class SetGroupKick(Action):
    _group_id: str
    _user_id: str

    def __call__(self) -> dict:
        return {
            "cls": GroupKick,
            "group_id": self._group_id,
            "user_id": self._user_id,
        }


class SetGroupBan(Action):
    _group_id: str
    _user_id: str
    _duration: int

    def __call__(self) -> dict:
        return {
            "cls": GroupBan,
            "group_id": self._group_id,
            "user_id": self._user_id,
            "duration": self._duration,
        }


def action_mapping(data: OB11ActionData) -> Union[list[MkIXPostMessage], dict]:
    print('Receive OB11 message')
    action = data.action
    actions = {
        "send_private_msg": SendPrivateMsg,
        "send_group_msg": SendGroupMsg,
        "send_msg": SendMsg,
        "delete_msg": DeleteMsg,
        "set_group_kick": SetGroupKick,
        "set_group_ban": SetGroupBan,
    }
    if action not in actions:
        raise ValueError("Unsupported Action")

    operation = actions[action](**data.params)()
    return operation

