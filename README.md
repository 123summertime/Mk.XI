# Mk.XI

## 介绍
`Mk.XI`是[OneBot v11](https://github.com/botuniverse/onebot-11)协议的实现，用于在[Mk.IX](https://github.com/123summertime/Mk.IX-Server)与聊天机器人框架之间进行通信

## 使用

安装运行所需的库
> pip install -r requirements.txt

修改`config.yaml`

> | 字段            | 默认                                | 功能                                            |
> |---------------|-----------------------------------|-----------------------------------------------|
> | account       |                                   | 账号                                            |
> | password      |                                   | 密码                                            |
> | server_url    | http://127.0.0.1:8000             | `Mk.IX`服务器地址                                  |
> | OneBot_url    | ws://127.0.0.1:8080/onebot/v11/ws | `OneBot Adapter`连接地址                          |
> | max_memo_size | 1024                              | 记录最近的`max_memo_size`条收发的消息，超出范围的无法被撤回         |
> | ssl_check     | true                              | 是否启用启用 `SSL/TLS` 证书验证，例如使用自签名证书则设为`false`     |
> | webp          | true                              | 图片转为`webp`再发送， 注意`Mk.IX `服务器默认图片大小上限为`2048KB` |
> | encrypt       |                                   | 需要加密的私/群聊，功能与前端的加密一致                          |


## 兼容性

### 接口
仅反向WebSocket

### CQ码

| CQ码         | 功能   | 备注                 |
|-------------|------|--------------------|
| [CQ:face]   | 发送表情 | qq表情将会使用相似的emoji代替 |
| [CQ:image]  | 发送图片 | 仅接受`file`字段        |
| [CQ:record] | 发送语音 | 仅接受`file`字段        |
| [CQ:at]     | @某人  |                    |
使用方法见`OneBot v11`[文档](https://github.com/botuniverse/onebot-11/blob/master/message/segment.md)

### API

#### OneBot标准API

| API                     | 功能       | 备注                                           |
|-------------------------|----------|----------------------------------------------|
| /send_private_msg       | 发送私聊消息   |                                              |
| /send_group_msg         | 发送群聊消息   |                                              |
| /send_msg               | 发送消息     |                                              |
| /send_group_msg         | 发送群聊消息   |                                              |
| /delete_msg             | 撤回消息     | 消息ID存储在内存中，无法撤回在运行前就已经产生的消息                  |
| /set_group_kick         | 踢出群聊     | `reject_add_request`字段无效                     |
| /set_group_ban          | 群禁言      |                                              |
| /set_group_admin        | 群组设置管理员  |                                              |
| /set_group_name         | 设置群名     |                                              |
| /set_group_leave        | 退/解散群    |                                              |
| /set_friend_add_request | 处理加好友请求  | `remark`字段无效                                 |
| /set_group_add_request  | 处理加群请求   | `sub_type`，`reason`字段无效                      |
| /get_login_info         | 获取自己账号信息 |                                              |
| /get_stranger_info      | 获取别人账号信息 | `no_cache`字段无效                               |
| /get_friend_list        | 获取好友列表   | 响应仅包含`user_id`                               |
| /get_group_info         | 获取群信息    | `no_cache`字段无效，响应`max_member_count`固定为`2000` |
| /get_group_list         | 获取群列表    | 响应仅包含`group_id`                              |
| /get_group_member_list  | 获取群员信息   | 响应仅包含`group_id`，`user_id`                    |
| /get_record             | 获取语音     | `out_format`字段无效                             |
| /get_image              | 获取图片     |                                              |
| /get_status             | 获取运行状态   |                                              |
| /get_version_info       | 获取版本信息   |                                              |
使用方法见`OneBot v11`[文档](https://github.com/botuniverse/onebot-11/blob/master/api/public.md)
> 可以传入无效的字段但不会产生作用，响应中缺失的字段会用空字符串或-1代替

#### go-cqhttp API
| API                       | 功能     | 备注                                |
|---------------------------|--------|-----------------------------------|
| /send_group_forward_msg   | 发送群聊消息 | 仅支持自定义消息发送，非转发形式，`name`和`uin`参数无效 |
| /send_private_forward_msg | 发送私聊消息 | 同上                                |
使用方法见`go-cqhttp`[文档](https://docs.go-cqhttp.org/api)

### Event
| Event  | post_type  | 备注                                  |
|--------|------------|-------------------------------------|
| 私聊消息   | message    |                                     |
| 群聊消息   | message    |                                     |
| 群文件上传  | notice     | 私聊文件上传也会触发                          |
| 群管理员变动 | notice     | 仅发生在机器人账号上时才会触发                     |
| 群成员减少  | notice     |                                     |
| 群成员增加  | notice     | `sub_type`的`invite`在这里指代通过回答入群问题入群的 |
| 群禁言    | notice     |                                     |
| 好友添加   | notice     |                                     |
| 群消息撤回  | notice     |                                     |
| 好友消息撤回 | notice     |                                     |
| 加好友请求  | request    |                                     |
| 加群请求   | request    | `sub_type`固定为`add`                  |
| 生命周期   | meta_event |                                     |
| 心跳     | meta_event |                                     |
具体信息见`OneBot v11`[文档](https://github.com/botuniverse/onebot-11/tree/master/event)
