import asyncio
import traceback
from typing import Awaitable
import json
from abc import ABC, abstractmethod

import websockets

from model import Config
from event import LifeCycle, HeartBeat


class WSConnect(ABC):
    _MAX_ATTEMPT = 3
    _attempt = 0

    def __init__(self, config: Config, message_callback: Awaitable):
        self._ws = None
        self._config = config
        self._message_callback = message_callback
        asyncio.create_task(self._connect())

    @abstractmethod
    async def _connect(self):
        pass

    async def _on_message(self, message):
        message = json.loads(message)
        asyncio.create_task(self._message_callback(message))

    async def _on_close(self, e):
        print("ws close", e)

    async def _on_error(self, e):
        print("ws error", e)
        # while self._attempt < self._MAX_ATTEMPT:
        #     try:
        #         await self._connect()
        #         return
        #     except Exception as e:
        #         print(f"Reconnect failed. Retry {self._attempt + 1} / {self._MAX_ATTEMPT}. Error: {e}")
        # print("All reconnect attempts failed")

    async def send(self, content):
        if self._ws:
            await self._ws.send(json.dumps(content))

    async def can_send(self) -> bool:
        try:
            waiter = await self._ws.ping()
            await waiter
            return True
        except Exception as e:
            print(e)
        return False


class MkIXConnect(WSConnect):
    def __init__(self, config: Config, message_callback: Awaitable, ws_token: str):
        self._ws_token = ws_token
        super().__init__(config, message_callback)

    async def _connect(self):
        url = f"{self._config.server_url.replace('http', 'ws')}/websocket/connect"
        headers = {"Authorization": self._ws_token}

        try:
            async with websockets.connect(url, additional_headers=headers) as websocket:
                self._ws = websocket
                self.attempt = 0
                async for message in websocket:
                    await self._on_message(message)
        except websockets.ConnectionClosed as e:
            await self._on_close(e)
        except Exception as e:
            await self._on_error(e)


class OneBotConnect(WSConnect):

    async def _connect(self):
        url = self._config.OneBot_url
        headers = {"X-Self-ID": self._config.account}

        async with websockets.connect(url, additional_headers=headers) as websocket:
            self._ws = websocket
            asyncio.create_task(self._lifecycle())
            asyncio.create_task(self._heartbeat())
            try:
                async for message in self._ws:
                    self.attempt = 0
                    await self._on_message(message)
            except websockets.ConnectionClosed as e:
                await self._on_close(e)
            except Exception as e:
                await self._on_error(e)

    async def _lifecycle(self):
        content = await LifeCycle(self._config.account)()
        asyncio.create_task(self.send(content))

    async def _heartbeat(self):
        while True:
            await asyncio.sleep(30)
            content = await HeartBeat(self._config.account)()
            asyncio.create_task(self.send(content))
