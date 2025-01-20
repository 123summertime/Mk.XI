import yaml
import traceback

from api import *
from ws import MkIXConnect, OneBotConnect
from model import Config, MyProfile, OB11ActionData
from event import event_mapping
from action import action_mapping, FriendAddRequest, GroupAddRequest
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
                config["encrypt"] = {str(k): v for k, v in config["encrypt"].items()}
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
        self._config.ws_check = self._MkIXConnect.can_send

        print("Set up success")

        # asyncio.create_task(self._fetcher.call(GetFriendRequest))
        # for i in self._my_profile.groups:
        #     asyncio.create_task(self._fetcher.call(GetGroupRequest, group=i))

    async def _mkix_message_handler(self, message):
        event = await event_mapping(message, self._launch_time, self._config, self._my_profile)
        if event:
            asyncio.create_task(self._OneBotConnect.send(event))

    async def _onebot_message_handler(self, message: dict):
        try:
            operation = action_mapping(OB11ActionData.model_validate(message))
            if isinstance(operation, list):     # 该Action通过ws发送
                message_id = await self._memo.post_messages(operation)
                asyncio.create_task(self._OneBotConnect.send({
                    'status': 'ok',
                    'retcode': 0,
                    'data': {'message_id': message_id},
                    'echo': message["echo"],
                }))
            elif isinstance(operation, dict):   # 该Action通过http发送
                ret = await self._fetcher.call(**operation)
                if operation["cls"] == FriendAddRequest and operation["approve"]:
                    self._my_profile.friends.add(operation["user_id"])
                elif operation["cls"] == GroupAddRequest and operation["approve"]:
                    self._my_profile.groups.add(operation["group_id"])
                asyncio.create_task(self._OneBotConnect.send({
                    'status': 'ok',
                    'retcode': 0,
                    'data': ret,
                    'echo': message["echo"],
                }))
        except Exception as e:
            print("Action error", e)
            print(traceback.print_exc())
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
