import asyncio
from typing import Awaitable
import json
from abc import ABC, abstractmethod

import websockets

from model import Config, MkIXGetMessage


class WSConnect(ABC):
    def __init__(self, config: Config, message_callback: Awaitable):
        self._ws = None
        self._config = config
        self._message_callback = message_callback
        asyncio.create_task(self._connect())

    @abstractmethod
    async def _connect(self):
        pass

    @abstractmethod
    async def _on_message(self, message):
        pass

    async def _on_close(self, e):
        print(e)

    async def _on_error(self, e):
        print(e)

    async def send(self, content):
        if self._ws:
            await self._ws.send(json.dumps(content))


class MkIXConnect(WSConnect):
    def __init__(self, config: Config, message_callback: Awaitable, ws_token: str):
        self._ws_token = ws_token
        super().__init__(config, message_callback)

    async def _connect(self):
        url = f"ws://{self._config.server_url}/websocket/connect"
        headers = {"Authorization": self._ws_token}

        try:
            async with websockets.connect(url, additional_headers=headers) as websocket:
                self._ws = websocket
                async for message in websocket:
                    await self._on_message(message)
        except websockets.ConnectionClosed as e:
            await self._on_close(e)
        except Exception as e:
            await self._on_error(e)

    async def _on_message(self, message):
        message = json.loads(message)
        await self._message_callback(message)


class OneBotConnect(WSConnect):

    async def _connect(self):
        url = self._config.OneBot_url
        headers = {"X-Self-ID": self._config.account}

        async with websockets.connect(url, additional_headers=headers) as websocket:
            self._ws = websocket
            try:
                async for message in self._ws:
                    await self._on_message(message)
            except websockets.ConnectionClosed as e:
                await self._on_close(e)
            except Exception as e:
                await self._on_error(e)

    async def _on_message(self, message):
        message = json.loads(message)
        await self._message_callback(message)

