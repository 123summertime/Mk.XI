import yaml
import traceback
from datetime import datetime
import asyncio

from api import *
from ws import MkIXConnect, OneBotConnect
from model import Config, MyProfile, MkIXGetMessage, OB11ActionData
from event import event_mapping
from action import action_mapping
from utils import MkIXMessageMemo, Tools


class MkXI:
    _memo: MkIXMessageMemo
    _config: Config
    _my_profile: MyProfile

    def __init__(self):
        self._load_config()

    def _load_config(self):
        try:
            with open('config.yaml', 'r', encoding='utf-8') as F:
                config = yaml.safe_load(F)
                self._config = Config.model_validate(config)
        except Exception as e:
            print("Error when loading config", e)

    async def _set_up(self):
        self._fetcher = FetchAPI(self._config).get_instance()
        res = await self._fetcher.call(Login)
        self._config.token = f"Bearer {res['access_token']}"
        res = await self._fetcher.call(WSToken)
        ws_token = res['token']
        res = await self._fetcher.call(GetMyProfile)
        res["groups"] = {i["group"] for i in res["groups"]}
        res["friends"] = {i["uuid"] for i in res["friends"]}
        self._my_profile = MyProfile.model_validate(res)

        self._MkIXConnect = MkIXConnect(self._config, self._mkix_message_handler, ws_token)
        self._OneBotConnect = OneBotConnect(self._config, self._onebot_message_handler)
        self._memo = MkIXMessageMemo(self._config, self._MkIXConnect).get_instance()
        self._launch_time = Tools.timestamp()
        print("Set up success")

    async def _mkix_message_handler(self, message):
        event = event_mapping(message, self._launch_time, self._config, self._my_profile)
        if event:
            asyncio.create_task(self._OneBotConnect.send(event))

    async def _onebot_message_handler(self, message: dict):
        try:
            operation = action_mapping(OB11ActionData.model_validate(message))
            if isinstance(operation, list):
                message_id = await self._memo.post_messages(operation)
                asyncio.create_task(self._OneBotConnect.send({
                    'status': 'ok',
                    'retcode': 0,
                    'data': {'message_id': message_id},
                    'echo': message["echo"],
                }))
            elif isinstance(operation, dict):
                ret = await self._fetcher.call(**operation)
                asyncio.create_task(self._OneBotConnect.send({
                    'status': 'ok',
                    'retcode': 0,
                    'data': ret,
                    'echo': message["echo"],
                }))
        except Exception as e:
            print("Action error", e)
            asyncio.create_task(self._OneBotConnect.send({
                'status': 'failed',
                'retcode': 1400,
                'data': {"detail": str(e)},
                'echo': message["echo"],
            }))

    async def run(self):
        try:
            await self._set_up()
            while True:
                await asyncio.sleep(5)
        except Exception as e:
            traceback.print_exc()
            print("Error during event loop", e)
