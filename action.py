from model import OB11ActionData, MkIXPostMessage, CQDataListItem, CQData, MkIXMessagePayload
from utils import CQCode
from typing import Union, Literal
from utils import MkIXMessageMemo
from api import *


class WSAction:

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


class SendPrivateMsg(WSAction):
    _user_id: str
    _message: Union[str, list]
    _auto_escape = False

    def _add_info(self, model_list: list[MkIXPostMessage]) -> None:
        for i in model_list:
            i.group = str(self._user_id)
            i.groupType = "friend"


class SendGroupMsg(WSAction):
    _group_id: str
    _message: Union[str, list]
    _auto_escape = False

    def _add_info(self, model_list: list[MkIXPostMessage]) -> None:
        for i in model_list:
            i.group = str(self._group_id)
            i.groupType = "group"


class SendMsg(WSAction):
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


class HTTPAction(ABC):

    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, '_' + k, v)

    @abstractmethod
    def __call__(self):
        raise NotImplementedError


class DeleteMsg(HTTPAction):
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


class SetGroupKick(HTTPAction):
    _group_id: str
    _user_id: str

    def __call__(self) -> dict:
        return {
            "cls": GroupKick,
            "group_id": self._group_id,
            "user_id": self._user_id,
        }


class SetGroupBan(HTTPAction):
    _group_id: str
    _user_id: str
    _duration: int = 30 * 60

    def __call__(self) -> dict:
        return {
            "cls": GroupBan,
            "group_id": self._group_id,
            "user_id": self._user_id,
            "duration": self._duration // 60,   # 单位: s
        }


class SetGroupAdmin(HTTPAction):
    _group_id: str
    _user_id: str
    _enable = True

    def __call__(self):
        return {
            "cls": GroupAdmin,
            "group_id": self._group_id,
            "user_id": self._user_id,
            "enable": self._enable,
        }


class SetGroupName(HTTPAction):
    _group_id: str
    _group_name: str

    def __call__(self):
        return {
            "cls": GroupName,
            "group_id": self._group_id,
            "group_name": self._group_name,
        }


class SetGroupLeave(HTTPAction):
    _group_id: str
    _is_dismiss = False

    def __call__(self):
        return {
            "cls": GroupLeave,
            "group_id": self._group_id,
            "is_dismiss": self._is_dismiss,
        }


class SetFriendAddRequest(HTTPAction):
    _user_id: str   # incompatible
    _flag: str
    _approve = True
    _remark: str

    def __call__(self):
        return {
            "cls": FriendAddRequest,
            "user_id": self._user_id,
            "flag": self._flag,
            "approve": self._approve,
        }


class SetGroupAddRequest(HTTPAction):
    _group_id: str  # incompatible
    _flag: str
    _sub_type: str
    _type: str
    _approve = True
    _reason: str

    def __call__(self):
        return {
            "cls": GroupAddRequest,
            "group_id": self._group_id,
            "flag": self._flag,
            "approve": self._approve,
        }


class GetLoginInfo(HTTPAction):

    def __call__(self):
        return {
            "cls": LoginInfo,
        }


class GetStrangerInfo(HTTPAction):
    _user_id: str

    def __call__(self):
        return {
            "cls": StrangerInfo,
            "user_id": self._user_id,
        }


class GetFriendList(HTTPAction):

    def __call__(self):
        return {
            "cls": FriendList,
        }


class GetGroupInfo(HTTPAction):
    _group_id: str

    def __call__(self):
        return {
            "cls": GroupInfo,
            "group_id": self._group_id,
        }


class GetGroupList(HTTPAction):

    def __call__(self):
        return {
            "cls": GroupList,
        }


class GetGroupMemberList(HTTPAction):
    _group_id: str

    def __call__(self):
        return {
            "cls": GroupMemberList,
            "group_id": self._group_id,
        }


class GetRecord(HTTPAction):
    _file: str
    _out_format: str

    def __call__(self):
        return {
            "cls": Record,
            "file": self._file,
        }


class GetImage(HTTPAction):
    _file: str
    _out_format: str

    def __call__(self):
        return {
            "cls": Image,
            "file": self._file,
        }


class GetStatus(HTTPAction):

    def __call__(self):
        return {
            "cls": Status,
        }


class GetVersionInfo(HTTPAction):

    def __call__(self):
        return {
            "cls": VersionInfo,
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
        "set_group_admin": SetGroupAdmin,
        "set_group_name": SetGroupName,
        "set_group_leave": SetGroupLeave,
        "set_friend_add_request": SetFriendAddRequest,
        "set_group_add_request": SetGroupAddRequest,
        "get_login_info": GetLoginInfo,
        "get_stranger_info": GetStrangerInfo,
        "get_friend_list": GetFriendList,
        "get_group_info": GetGroupInfo,
        "get_group_list": GetGroupList,
        "get_group_member_list": GetGroupMemberList,
        "get_record": GetRecord,
        "get_image": GetImage,
        "get_status": GetStatus,
        "get_version_info": GetVersionInfo,
    }
    if action not in actions:
        raise ValueError("Unsupported Action")

    operation = actions[action](**data.params)()
    return operation

