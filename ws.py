import ssl
import json
import asyncio
from abc import ABC, abstractmethod
from math import inf
from typing import Awaitable

import websockets

from api import WSToken, FetchAPI
from utils import Tools
from model import Config
from event import LifeCycle, HeartBeat

TIMEOUT = inf
RETRY_INTERVAL = 5
WS_FRAME_MAX_SIZE = 1 << 23  # 8MB


class WSConnect(ABC):

    def __init__(self, config: Config, message_callback: Awaitable):
        self._ws = None
        self._ok = False
        self._config = config
        self._message_callback = message_callback

    @classmethod
    async def create(cls, config: Config, message_callback: Awaitable):
        is_success = asyncio.Future()
        instance = cls(config, message_callback)
        asyncio.create_task(instance._connect(is_success))
        await asyncio.wait_for(is_success, inf)
        return instance

    @abstractmethod
    async def _connect(self, future: asyncio.Future):
        pass

    async def _on_message(self, message):
        message = json.loads(message)
        asyncio.create_task(self._message_callback(message))

    async def _on_close(self, e):
        Tools.logger().error(f"WS closed: {e}")

    async def _on_error(self, e):
        Tools.logger().error(f"WS error: {e}")

    async def send(self, content):
        if self._ws:
            await self._ws.send(json.dumps(content))

    async def can_send(self) -> bool:
        try:
            waiter = await self._ws.ping()
            await waiter
            return True
        except Exception:
            pass
        return False


class MkIXConnect(WSConnect):

    async def _connect(self, future: asyncio.Future):
        fetcher = FetchAPI.get_instance()
        url = f"{self._config.server_url.replace('http', 'ws')}/websocket/connect"

        ssl_context = None
        if not self._config.ssl_check:
            ssl_context = ssl.create_default_context()
            ssl_context.check_hostname = False
            ssl_context.verify_mode = ssl.CERT_NONE

        while True:
            try:
                res = await fetcher.call(WSToken)
                headers = {"Authorization": res['token']}
                async with websockets.connect(url,
                                              additional_headers=headers,
                                              ssl=ssl_context,
                                              max_size=WS_FRAME_MAX_SIZE) as websocket:
                    Tools.logger().info("MkIXConnect Success")
                    if not future.done():
                        future.set_result(None)
                    self._ok = True
                    self._ws = websocket
                    async for message in websocket:
                        await self._on_message(message)
            except websockets.ConnectionClosed as e:
                await self._on_close(e)
            except Exception as e:
                await self._on_error(e)

            Tools.logger().error("MkIXConnect Error. Retrying...")
            self._ok = False
            await asyncio.sleep(RETRY_INTERVAL)


class OneBotConnect(WSConnect):

    async def _connect(self, future: asyncio.Future):
        url = self._config.OneBot_url
        headers = {
            "X-Self-ID": self._config.account,
            "X-Client-Role": "Universal",
        }

        while True:
            try:
                async with websockets.connect(url,
                                              additional_headers=headers,
                                              max_size=WS_FRAME_MAX_SIZE) as websocket:
                    Tools.logger().info("OneBotConnect Success")
                    if not future.done():
                        future.set_result(None)
                    self._ok = True
                    self._ws = websocket
                    asyncio.create_task(self._lifecycle())
                    asyncio.create_task(self._heartbeat())
                    async for message in self._ws:
                        await self._on_message(message)
            except websockets.ConnectionClosed as e:
                await self._on_close(e)
            except Exception as e:
                await self._on_error(e)

            Tools.logger().error("OneBotConnect Error. Retrying...")
            self._ok = False
            await asyncio.sleep(RETRY_INTERVAL)

    async def _lifecycle(self):
        content = await LifeCycle(self._config.account)()
        asyncio.create_task(self.send(content))

    async def _heartbeat(self):
        while True:
            await asyncio.sleep(30)
            if self._ok:
                content = await HeartBeat(self._config.account)()
                asyncio.create_task(self.send(content))
