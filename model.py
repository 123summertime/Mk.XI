import hashlib
from typing import Optional, Any, Literal, Union

from pydantic import BaseModel, validator


class Config(BaseModel):
    account: str
    password: str
    server_url: str
    OneBot_url: str
    max_memo_size: int
    ssl_check: bool
    webp: bool
    encrypt: dict[str, str]

    token: str = ""
    ws_check: Any = None

    @validator("account", pre=True)
    def _convert_account(cls, v):
        return str(v)

    @validator("password", pre=True)
    def _convert_password(cls, v):
        return hashlib.md5(str(v).encode()).hexdigest()

    @validator("max_memo_size", pre=True)
    def _convert_max_memo_size(cls, v):
        return int(v)


class MyProfile(BaseModel):
    uuid: str
    username: str
    bio: str
    lastUpdate: str
    groups: set[str]
    friends: set[str]


class Message(BaseModel):
    pass


class MkIXMessagePayload(Message):
    name: Optional[str] = None
    size: Optional[int] = None
    content: Union[str, bytes] = ""
    meta: dict[str, Any] = {}

    def __or__(self, other: 'MkIXMessagePayload') -> 'MkIXMessagePayload':
        if not isinstance(other, MkIXMessagePayload):
            return NotImplemented

        meta = self.meta.copy()
        for k, v in other.meta.items():
            if k in meta:
                meta[k] += v
            else:
                meta[k] = v

        return MkIXMessagePayload(
            name=self.name or other.name,
            size=self.size or other.size,
            content=self.content + other.content,
            meta=meta,
        )


class MkIXGetMessage(Message):
    time: str
    type: str
    group: str
    isSystemMessage: bool
    senderID: str
    payload: MkIXMessagePayload


class MkIXPostMessage(BaseModel):
    type: Optional[str] = None
    echo: Optional[int] = None
    group: Optional[str] = None
    groupType: Literal["group", "friend", ""] = ""
    payload: Optional[MkIXMessagePayload] = None

    def __or__(self, other: 'MkIXPostMessage') -> 'MkIXPostMessage':
        if not isinstance(other, MkIXPostMessage):
            return NotImplemented

        if self.payload and other.payload:
            payload = self.payload | other.payload
        else:
            payload = self.payload or other.payload

        return MkIXPostMessage(
            type=self.type or other.type,
            group=self.group or other.group,
            groupType=self.groupType or other.groupType,
            payload=payload,
        )


class MkIXSystemMessage(BaseModel):
    time: str
    type: str
    subType: Optional[str] = None
    target: Optional[str] = None
    targetKey: Optional[str] = None
    isSystemMessage: bool = True
    state: Optional[str] = None
    senderID: Optional[str] = None
    senderKey: Optional[str] = None
    payload: str
    meta: Optional[dict] = dict()


class OB11ActionData(BaseModel):
    action: str
    params: dict[str, Any]


class CQData(BaseModel):
    data: str


class CQDataListItem(BaseModel):
    type: str
    data: dict
