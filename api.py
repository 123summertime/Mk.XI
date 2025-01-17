import re
import json
from abc import ABC, abstractmethod
import asyncio
import base64
import os
import aiofiles
import uuid
import httpx
from model import Config
from typing import Type, Optional


class API(ABC):

    def __init__(self, config: Config):
        self._config = config

    def _build_url(self, endpoint: str, **params):
        query = '&'.join(f"{k}={v}" for k, v in params.items())
        return f"http://{self._config.server_url}/{endpoint}?{query}"

    def _response_handler(self, res: httpx.Response) -> dict:
        content = json.loads(res.content.decode())
        if res.status_code >= 300:
            raise RuntimeError(f"HTTP {res.status_code} detail={content['detail']}")
        return content

    async def _fetch(
            self,
            method: str,
            url: str,
            *,
            data: str = None,
            headers: dict[str, str] = None,
            payload: dict[str, str] = None,
            files: dict = None,
            timeout: int = 5,
    ) -> httpx.Response:
        kwargs = {
            "method": method.upper(),
            "url": url,
            "headers": headers,
            "data": data,
            "json": payload,
            "files": files,
            "timeout": timeout,
        }

        async with httpx.AsyncClient() as client:
            try:
                res = await client.request(**kwargs)
            except Exception as e:
                print("Fetch error:", e)
        return res

    @abstractmethod
    async def __call__(self, *args, **kwargs):
        raise NotImplementedError


class Login(API):

    async def __call__(self, *args, **kwargs):
        res = await self._fetch(
            "POST",
            self._build_url('v1/user/token', isBot=True),
            data=f"grant_type=password&username={self._config.account}&password={self._config.password}",
            headers={'Content-Type': 'application/x-www-form-urlencoded'}
        )
        return self._response_handler(res)


class WSToken(API):

    async def __call__(self, *args, **kwargs):
        res = await self._fetch(
            "GET",
            self._build_url('v1/user/wsToken', device="00000000"),
            headers={"Authorization": self._config.token}
        )
        return self._response_handler(res)


class GetMyProfile(API):

    async def __call__(self, *args, **kwargs):
        res = await self._fetch(
            "GET",
            self._build_url('v1/user/profile/me'),
            headers={"Authorization": self._config.token}
        )
        return self._response_handler(res)


class PostFile(API):

    async def __call__(self, *args, **kwargs):
        group, group_type, payload, payload_type = kwargs["group"], kwargs["group_type"], kwargs["payload"], kwargs["payload_type"]
        group_type = 'group' if group_type == 'group' else 'user'
        form_data = {
            "file": ("file", payload),
            "fileType": (None, payload_type),
            "groupType": (None, group_type),
        }
        res = await self._fetch(
            "POST",
            self._build_url(f"v1/{group_type}/{group}/upload"),
            headers={"Authorization": self._config.token},
            files=form_data,
        )
        return self._response_handler(res)


class GroupKick(API):

    async def __call__(self, *args, **kwargs):
        group_id, user_id = kwargs["group_id"], kwargs["user_id"]
        res = await self._fetch(
            "DELETE",
            self._build_url(f"v1/group/{group_id}/members/{user_id}"),
            headers={"Authorization": self._config.token},
        )
        return self._response_handler(res)


class GroupBan(API):

    async def __call__(self, *args, **kwargs):
        group_id, user_id, duration = kwargs["group_id"], kwargs["user_id"], int(kwargs["duration"])
        res = await self._fetch(
            "POST",
            self._build_url(f"v1/group/{group_id}/members/{user_id}/ban"),
            headers={"Authorization": self._config.token},
            payload={"duration": duration},
        )
        return self._response_handler(res)


class GroupAdmin(API):

    async def __call__(self, *args, **kwargs):
        group_id, user_id, enable = kwargs["group_id"], kwargs["user_id"], kwargs["enable"]
        res = await self._fetch(
            "POST" if enable else "DELETE",
            self._build_url(f"v1/group/{group_id}/members/admin/{user_id}"),
            headers={"Authorization": self._config.token},
        )
        return self._response_handler(res)


class GroupName(API):

    async def __call__(self, *args, **kwargs):
        group_id, group_name = kwargs["group_id"], kwargs["group_name"]
        res = await self._fetch(
            "PATCH",
            self._build_url(f"v1/group/{group_id}/info/name"),
            headers={"Authorization": self._config.token},
            payload={"name": group_name},
        )
        return self._response_handler(res)


class GroupLeave(API):

    async def __call__(self, *args, **kwargs):
        group_id, is_dismiss = kwargs["group_id"], kwargs["is_dismiss"]
        res = await self._fetch(
            "DELETE",
            self._build_url(f"v1/group/{group_id}") if is_dismiss else self._build_url(f"v1/group/{group_id}/members/me"),
            headers={"Authorization": self._config.token},
        )
        return self._response_handler(res)


class FriendAddRequest(API):

    async def __call__(self, *args, **kwargs):
        user_id, flag, approve = kwargs['user_id'], kwargs['flag'], kwargs.get('approve', True)
        res = await self._fetch(
            "POST" if approve else "DELETE",
            self._build_url(f"v1/user/{user_id}/verify/request/{flag}"),
            headers={"Authorization": self._config.token},
        )
        return self._response_handler(res)


class GroupAddRequest(API):

    async def __call__(self, *args, **kwargs):
        group_id, flag, approve = kwargs['group_id'], kwargs['flag'], kwargs.get('approve', True)
        res = await self._fetch(
            "POST" if approve else "DELETE",
            self._build_url(f"v1/group/{group_id}/verify/request/{flag}"),
            headers={"Authorization": self._config.token},
        )
        return self._response_handler(res)


class LoginInfo(API):

    async def __call__(self, *args, **kwargs):
        res = await self._fetch(
            "GET",
            self._build_url('v1/user/profile/me'),
            headers={"Authorization": self._config.token}
        )
        ret = self._response_handler(res)
        return {
            "user_id": ret["uuid"],
            "nickname": ret["username"]
        }


class StrangerInfo(API):

    async def __call__(self, *args, **kwargs):
        user_id = kwargs["user_id"]
        res = await self._fetch(
            "GET",
            self._build_url(f'v1/user/{user_id}/profile'),
        )
        ret = self._response_handler(res)
        return {
            "user_id": user_id,
            "nickname": ret["username"],
            "sex": "unknown",   # helicopter(bushi)
            "age": -1,
            "avatar": ret["avatar"],
        }


class FriendList(API):

    async def __call__(self, *args, **kwargs):
        res = await self._fetch(
            "GET",
            self._build_url('v1/user/profile/me'),
            headers={"Authorization": self._config.token}
        )
        ret = self._response_handler(res)
        return [{
            "user_id": i["uuid"],
            "nickname": "",
            "remark": "",
        } for i in ret["friends"]]


class GroupInfo(API):

    async def __call__(self, *args, **kwargs):
        group_id = kwargs["group_id"]
        res0 = await self._fetch(
            "GET",
            self._build_url(f'v1/group/{group_id}/info')
        )
        ret0 = self._response_handler(res0)
        res1 = await self._fetch(
            "GET",
            self._build_url(f'v1/group/{group_id}/members'),
            headers={"Authorization": self._config.token}
        )
        ret1 = self._response_handler(res1)
        return {
            "group_id": group_id,
            "group_name": ret0["name"],
            "member_count": len(ret1["users"]),
            "max_member_count": 2000,
        }


class GroupList(API):

    async def __call__(self, *args, **kwargs):
        res = await self._fetch(
            "GET",
            self._build_url('v1/user/profile/me'),
            headers={"Authorization": self._config.token}
        )
        ret = self._response_handler(res)
        return [{
            "group_id": i["group"],
            "group_name": "",
            "member_count": -1,
            "max_member_count": -1,
        } for i in ret["groups"]]


class GroupMemberInfo(API):
    ...


class GroupMemberList(API):

    async def __call__(self, *args, **kwargs):
        group_id = kwargs["group_id"]
        res = await self._fetch(
            "GET",
            self._build_url(f'v1/group/{group_id}/members'),
            headers={"Authorization": self._config.token}
        )
        ret = self._response_handler(res)
        return [{
            "group_id": group_id,
            "user_id": i["uuid"],
        } for i in ret["members"]]


class APIWithFileIO(API):
    _save_path = './downloads'


class Record(APIWithFileIO):

    async def __call__(self, *args, **kwargs):
        file = kwargs["file"]  # download url
        if not file.startswith(self._build_url("v1")[:-1]):
            raise ValueError("Unknown domain")

        res = await self._fetch(
            "GET",
            file,
            headers={"Authorization": self._config.token},
        )
        if res.status_code >= 300:
            content = json.loads(res.content.decode())
            raise RuntimeError(f"HTTP {res.status_code} detail={content['detail']}")

        os.makedirs(self._save_path, exist_ok=True)
        file_path = os.path.join(self._save_path, file.split('/')[-1] + '.mp3')
        absolute_path = os.path.abspath(file_path)
        async with aiofiles.open(file_path, "wb") as f:
            await f.write(res.content)

        return {"file": absolute_path}


class Image(APIWithFileIO):

    async def __call__(self, *args, **kwargs):
        file = kwargs["file"]  # base64
        if not file.startswith("base64://"):
            raise ValueError("Invalid base64. Must start with base64://")

        try:
            data = base64.b64decode(file.split(',')[1])
        except Exception as e:
            raise ValueError("Decode error")

        match = re.search(r"data:image/(\w+);base64", file)
        extract_type = match.group(1) if match else "png"
        os.makedirs(self._save_path, exist_ok=True)
        file_path = os.path.join(self._save_path, f"{uuid.uuid4().hex}.{extract_type}")
        absolute_path = os.path.abspath(file_path)
        async with aiofiles.open(file_path, "wb") as f:
            await f.write(data)

        return {"file": absolute_path}


class Status(API):

    async def __call__(self, *args, **kwargs):
        status = await self._config.ws_check()
        return {
            "online": status,
            "good": status,
        }


class VersionInfo(API):

    async def __call__(self, *args, **kwargs):
        return {
            "app_name": "MkXI",
            "app_version": "1.0.0",
            "protocol_version": "v11",
        }


class CleanCache(APIWithFileIO):
    ...


class FetchAPI:
    _instance = None

    def __init__(self, config: Config):
        if FetchAPI._instance is not None:
            raise ValueError("Already instantiated")
        self._config = config
        FetchAPI._instance = self

    @classmethod
    def get_instance(cls) -> 'FetchAPI':
        if cls._instance is None:
            raise ValueError("Not instantiated yet")
        return cls._instance

    async def call(self, cls: Type[API], **kwargs) -> Optional[dict]:
        return await cls(self._config)(**kwargs)
