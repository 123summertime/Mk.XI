import re
import os
import json
import base64
import asyncio
import logging
import mimetypes
from io import BytesIO
from math import inf
from typing import Union, Literal, Optional, TYPE_CHECKING
from datetime import datetime
from collections import deque
from urllib.parse import urlparse

import httpx
from PIL import Image
from rich.logging import RichHandler
from Crypto.Cipher import AES
from Crypto.Random import get_random_bytes
from Crypto.Util.Padding import pad

from api import PostFile, FetchAPI
from model import MkIXGetMessage, CQData, CQDataListItem, MkIXMessagePayload, MkIXPostMessage, Config, MkIXSystemMessage

if TYPE_CHECKING:
    from ws import MkIXConnect

TIME_LIMIT_TEXT = 1
TIME_LIMIT_IMG = 3
TIME_LIMIT_FILE = 10


class RichHandlerCut(RichHandler):
    def emit(self, record):
        if isinstance(record.msg, str) and len(record.msg) > 500:
            record.msg = record.msg[:500] + "..."
        super().emit(record)


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[RichHandlerCut()]
)
logger = logging.getLogger("rich_logger")
logger.setLevel(logging.INFO)


class MkIXMessageMemo:
    """ 发送及确认消息，记录发送的消息id """
    _instance = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            cls._instance = super(MkIXMessageMemo, cls).__new__(cls)
        return cls._instance

    def __init__(self, config: Config, ws: 'MkIXConnect'):
        if not hasattr(self, "_initialized"):
            self._initialized = True
            self._config = config
            self._ws = ws
            self._echo_id = 0
            self._wait_echo: dict[int, asyncio.Future] = {}
            self._message_chunk: dict[str, list[str]] = dict()  # message_id -> [message_id_0, message_id_1, ...]
            self._message_group_type: dict[str, tuple[Literal["group", "friend"], str]] = dict()  # message_id -> (group_type, group_id)
            self._message_queue = asyncio.Queue(maxsize=64)  # 消息队列
            self._capacity_queue = deque()  # 到达最大记忆容量后pop过期数据，最大容量为config.max_memo_size
            self._consumer = asyncio.create_task(self._dequeue())

    @classmethod
    def get_instance(cls) -> 'MkIXMessageMemo':
        if cls._instance:
            return cls._instance
        raise ValueError("Not instantiated yet")

    def receive_chat(self, message: MkIXGetMessage, group_type: Literal["group", "friend"]) -> None:
        self._message_group_type[message.time] = (group_type, message.group)
        self._message_chunk[message.time] = [message.time]
        self._capacity_queue.append(message.time)
        if len(self._capacity_queue) >= self._config.max_memo_size:
            message_id = self._capacity_queue.popleft()
            if message_id in self._message_group_type:
                del self._message_group_type[message_id]
            for i in self._message_chunk.get(message_id, []):
                if i in self._message_chunk:
                    del self._message_chunk[i]

    def receive_echo(self, message: MkIXSystemMessage) -> None:
        echo = json.loads(message.payload)
        echo_id = echo["echo"]
        if echo_id in self._wait_echo:
            future = self._wait_echo[echo_id]
            future.set_result(echo["time"])
            del self._wait_echo[echo_id]

    def get_storage(self, message_id: str) -> tuple[Literal["group", "friend"], str, list[str]]:
        if message_id not in self._message_group_type:
            raise KeyError(f"message_id: {message_id} not found")

        group_type, group_id = self._message_group_type[message_id]
        messages = self._message_chunk[message_id]
        for i in messages:
            del self._message_chunk[i]
        del self._message_group_type[message_id]

        return group_type, str(group_id), messages

    async def post_messages(self, messages: list[MkIXPostMessage], action: str) -> int:
        future = asyncio.Future()
        await self._message_queue.put((messages, future))
        ret = await asyncio.wait_for(future, timeout=30)
        mapping = {
            "send_private_forward_msg": {"message_id": ret, "forward_id": ret},
            "send_group_forward_msg": {"message_id": ret, "forward_id": ret},
        }
        return mapping.get(action, {"message_id": ret})

    async def _dequeue(self):
        while True:
            batch = await self._message_queue.get()
            try:
                await self._process_messages(batch)
            except Exception as e:
                Tools.logger().error(f"Error processing messages: {e}")
            finally:
                self._message_queue.task_done()

    async def _process_messages(self, batch: tuple[list[MkIXPostMessage], asyncio.Future]):
        messages, future = batch
        message_ids = []
        for idx, i in enumerate(messages):
            i.echo = self._echo_id
            res = None
            if i.type in ("file", "audio"):
                fetcher = FetchAPI.get_instance()
                try:
                    res = await fetcher.call(
                        PostFile,
                        group=i.group,
                        group_type=i.groupType,
                        payload=i.payload.content,
                        payload_type=i.type,
                    )
                    res = res["time"]
                except Exception as e:
                    Tools.logger().error(f"Upload File Error: {e}")
            else:
                if i.type == "image" and self._config.webp:
                    i.payload.content = Tools.webp_b64(i.payload.content)
                if i.type in ("text", "image") and i.group in self._config.encrypt:
                    Tools.encrypt(self._config, i)
                asyncio.create_task(self._ws.send(i.model_dump()))
                res = await self._wait_for_echo(i.echo, Tools.time_limit(i.type))

            if res:
                Tools.logger().info(f"#{self._echo_id} Success")
                message_ids.append(res)
            else:
                Tools.logger().error(f"#{self._echo_id} Failed")
            self._echo_id += 1

        for i in message_ids:
            self._message_chunk[i] = message_ids

        success_count = len(message_ids)
        if success_count == 0:
            future.set_result(-1)
            raise Exception("All failed")
        else:
            future.set_result(message_ids[0])

    async def _wait_for_echo(self, echo_id: int, time_limit: int) -> Optional[str]:
        future = asyncio.Future()
        self._wait_echo[echo_id] = future
        try:
            return await asyncio.wait_for(future, timeout=time_limit)
        except Exception as e:
            Tools.logger().error(f"#{echo_id} Timeout: {e}")
            del self._wait_echo[echo_id]
            return None


class CQCode:

    @classmethod
    def serialization(cls,
                      message: MkIXGetMessage,
                      config: Optional[Config] = None,
                      format_type: Literal["string", "array"] = "array",
                      group_type: Optional[Literal["group", "private"]] = None) -> Union[str, list]:

        if format_type == "string":
            convert = ""
            for at in message.payload.meta.get("at", []):
                convert += f"[CQ:at,qq={at}]"
            if message.type == "text":
                convert += message.payload.content
            elif message.type == "image":
                convert += f"[CQ:image,file={message.payload.content}]"
            elif message.type in ("file", "audio"):
                if not config or not group_type:
                    raise ValueError("Parameters 'config' and 'group_type' must be provided for file/audio types")
                group_type = 'group' if group_type == 'group' else 'user'
                url = f"{config.server_url}/v1/{group_type}/{message.group}/download/{message.payload.content}"
                convert += f"[CQ:{message.type if message.type == 'file' else 'record'},file={url}]"
            return convert

        if format_type == "array":
            convert = []
            for at in message.payload.meta.get("at", []):
                convert.append({
                    "type": "at",
                    "data": {"qq": at},
                })
            if message.type == "text":
                convert.append({
                    "type": "text",
                    "data": {"text": message.payload.content},
                })
            elif message.type == "image":
                convert.append({
                    "type": "image",
                    "data": {"file": message.payload.content},
                })
            elif message.type in ("file", "audio"):
                if not config or not group_type:
                    raise ValueError("Parameters 'config' and 'group_type' must be provided for file/audio types")
                group_type = 'group' if group_type == 'group' else 'user'
                url = f"{config.server_url}/v1/{group_type}/{message.group}/download/{message.payload.content}"
                convert.append({
                    "type": message.type if message.type == 'file' else 'record',
                    "data": {"file": url},
                })
            return convert

        raise ValueError("Invalid parameter: format_type")

    @classmethod
    def deserialization(cls,
                        message: Union[CQData, list[CQDataListItem]],
                        auto_escape: bool = False) -> list[MkIXPostMessage]:
        segments = []
        if isinstance(message, CQData) and auto_escape:
            segments.append(CQDataListItem(type="text", data={"text": message.data}))
        elif isinstance(message, CQData):
            res = re.split(r"(\[.*?])", message.data)
            for i in res:
                if not i:
                    continue

                data = {"data": {}}
                if i[0] == '[' and i[-1] == ']':    # CQ码
                    i = i[1:-1]
                    type_, *params = i.split(',')
                    data["type"] = type_[3:]
                    for param in params:
                        k, v = param.split("=", 1)
                        data["data"][k] = v
                else:   # 普通文字
                    data["type"] = "text"
                    data["data"]["text"] = i
                segments.append(CQDataListItem.model_validate(data))
        else:
            segments = message

        stack: list[MkIXPostMessage] = []
        for x in segments:
            x = cls._type_match(x)
            if stack and stack[-1].type == "text" and x.type == "text":
                stack[-1] |= x
            else:
                stack.append(x)
        return stack

    @classmethod
    def _type_match(cls, model: CQDataListItem) -> MkIXPostMessage:
        method_mapping = {
            "at": cls._at_handler,
            "text": cls._text_handler,
            "file": cls._file_handler,
            "face": cls._face_handler,
            "image": cls._image_handler,
            "record": cls._file_handler,
        }

        if model.type not in method_mapping:
            raise TypeError(f"Invalid type: {model.type}")

        type_mapping = {
            "at": "text",
            "face": "text",
            "record": "audio",
        }

        convert: MkIXPostMessage = method_mapping[model.type](**(model.data))
        convert.type = type_mapping.get(model.type, model.type)
        return convert

    @classmethod
    def _at_handler(cls, qq: int) -> MkIXPostMessage:
        return MkIXPostMessage(
            payload=MkIXMessagePayload(
                meta={"at": [str(qq)]}
            )
        )

    @classmethod
    def _text_handler(cls, text: str) -> MkIXPostMessage:
        return MkIXPostMessage(
            payload=MkIXMessagePayload(
                content=text
            )
        )

    @classmethod
    def _extract_file(cls,
                      file: str,
                      *,
                      b64_output: bool = False,
                      **kwargs) -> MkIXPostMessage:
        model = MkIXPostMessage(
            payload=MkIXMessagePayload()
        )

        def encode_to_base64(content, mime):
            if not mime:
                mime = "application/octet-stream"
            return f"data:{mime};base64," + base64.b64encode(content).decode('utf-8')

        if file.startswith("base64://"):
            prefix = len("base64://")
            decoded_content = base64.b64decode(file[prefix:], validate=True)
            model.payload.content = (
                encode_to_base64(decoded_content, "application/octet-stream") if b64_output else decoded_content
            )
            return model

        parsed = urlparse(file)
        if parsed.scheme in ('file', ''):
            file_path = parsed.path[1:]
            if os.path.exists(file_path):
                with open(file_path, 'rb') as f:
                    content = f.read()
                    model.payload.content = (
                        encode_to_base64(content, mimetypes.guess_type(file_path)[0]) if b64_output else content
                    )
                    return model
            else:
                raise FileNotFoundError(f"File not found: {file_path}")

        if parsed.scheme in ('http', 'https'):
            res = httpx.get(file)
            res.raise_for_status()
            content = res.content
            model.payload.content = (
                encode_to_base64(content, res.headers.get('Content-Type', None)) if b64_output else content
            )
            return model

        raise ValueError("Invalid URI / URL / Base64, skipping...")

    @classmethod
    def _image_handler(cls, file: str, **kwargs) -> MkIXPostMessage:
        return cls._extract_file(file, b64_output=True)

    @classmethod
    def _file_handler(cls, file: str, **kwargs) -> MkIXPostMessage:
        return cls._extract_file(file, b64_output=False)

    @classmethod
    def _face_handler(cls, id: int) -> MkIXPostMessage:
        # 10个一行
        mapping = [
            ('😲', '😖', '🥰', '🥲', '😎', '😭', '😊', '🤐', '😪', '😢'),
            ('😡', '🤬', '😛', '😁', '😊', '😣', '😎', ' ', '😫', '🤮'),
            ('🫢', '😊', '😶', '😕', '😜', '🥱', '😰', '😅', '😀', '🤠'),
            ('🤓', '🤪', '🤔', '🤫', '😵', '😵', '🥶', '💀', '😰', '🤗'),
            (' ', '🫨', '💓', '🤣', ' ', ' ', '🐷', ' ', ' ', '🤗'),

            (' ', ' ', ' ', '🎂', '⚡', '💣', '🔪', '⚽', ' ', '💩'),
            ('☕', '🍚', '💊', '🌹', '🥀', ' ', '❤️', '💔', ' ', '🎁'),
            (' ', ' ', '✉️', ' ', '☀️', '🌙', '👍', '👎', '🤝', '✌️'),
            (' ', ' ', ' ', ' ', ' ', '😘', '🤪', ' ', ' ', '🍉'),
            ('🌧️', '☁️', ' ', ' ', ' ', ' ', '😥', '😓', '🙄', '👏'),

            ('😥', '😁', '😏', '😏', '🫢', '👎', '😔', '😔', '😅', '😘'),
            ('😲', '🥹', '🔪', '🍺', '🏀', '🏓', '👄', '🐞', '👍', '🫵'),
            ('✊', '👆', '🤘', '👆', '👌', '😉', '☺️', '😏', '🙂', '👋'),
            ('😂', '😮', '🫢', '🙂', '🙂', ' ', '❤️', '🧨', '🏮', '🤑'),
            ('🎤', '💼', '✉️', '🔴', '💐', '🕯️', '💢', '🍭', '🍼', '🍜'),

            ('🍌', '✈️', '🚙', '🚅', '🚅', '🚅', '☁️', '🌧️', '💵', '🐼'),
            ('💡', '🪁', '⏰', '☂️', '🎈', '💍', '🛋️', '🧻', '💊', '🔫'),
            ('🐸', '🍵', '😜', '😢', '😛', '😝', '😌', '😡', '😊', '😗'),
            ('😲', '🥺', '😂', '😝', '🦀', '🦙', '🌰', '👻', '🥚', '📱'),
            ('🏵️', '🧼', '🧧', '🤤', '😕', ' ', ' ', '🙄', '🫢', '👏'),

            ('🙏', '👍', '😊', '😛', '😯', '🌹', '😅', '🥰', '😡', ' '),
            ('😂', '🫣', '😐', '😘', '💩', '👊', '😐', '😛', '🥳', '🥸'),
            ('👍', ' ', ' ', ' ', ' ', ' ', ' ', ' ', ' ', ' '),
        ]

        row, col = divmod(int(id), 10)
        if row < len(mapping):
            return MkIXPostMessage(
                payload=MkIXMessagePayload(
                    content=mapping[row][col]
                )
            )
        else:
            raise ValueError(f"Invalid face_id: {id}, skipping...")


class RequestMemo:
    _instance = None

    def __init__(self):
        if RequestMemo._instance is not None:
            raise ValueError("Already instantiated")
        self._friend_request = dict()
        self._group_request = dict()
        RequestMemo._instance = self

    @classmethod
    def get_instance(cls) -> 'RequestMemo':
        if cls._instance is None:
            raise ValueError("Not instantiated yet")
        return cls._instance

    def put(self, msg: MkIXSystemMessage):
        if msg.state == "等待审核" and msg.type == "join":
            self._group_request[msg.time] = msg.target
        if msg.state == "等待审核" and msg.type == "friend":
            self._friend_request[msg.time] = msg.target

    def get(self, id: str, type: Literal["group", "friend"]):
        try:
            id = str(id)
            if type == "group":
                return self._group_request[id]
            if type == "friend":
                return self._friend_request[id]
        except KeyError:
            raise KeyError(f"Invalid flag: {id}")
        raise ValueError(f"Invalid type: {type}")


class Tools:

    @staticmethod
    def timestamp() -> str:
        return "{:.3f}".format(datetime.now().timestamp()).replace(".", "")

    @staticmethod
    def encrypt(config: Config, msg: MkIXPostMessage) -> None:
        s = msg.payload.content.encode('utf-8')
        key = config.encrypt[msg.group].encode('utf-8')
        iv = get_random_bytes(16)
        cipher = AES.new(key, AES.MODE_CBC, iv)
        encrypted = cipher.encrypt(pad(s, 16))
        encrypted = base64.b64encode(encrypted).decode('utf-8')

        msg.payload.content = encrypted
        msg.payload.meta["encrypt"] = True
        msg.payload.meta["iv"] = iv.hex()

    @staticmethod
    def webp_b64(s: str) -> str:
        try:
            img = base64.b64decode(s.split(',')[1])
            image = Image.open(BytesIO(img))
            buffer = BytesIO()
            image.save(buffer, format="WEBP")
            webp = base64.b64encode(buffer.getvalue()).decode("utf-8")
            return f"data:image/webp;base64,{webp}"
        except Exception as e:
            Tools.logger().error(f"Convert image error: {e}")
            return s

    @staticmethod
    def time_limit(t: str) -> int:
        if t in ("text", "revokeRequest"):
            return TIME_LIMIT_TEXT
        if t == "image":
            return TIME_LIMIT_IMG
        return TIME_LIMIT_FILE

    @staticmethod
    def logger():
        return logger
