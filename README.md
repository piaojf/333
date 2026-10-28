# 本地键值服务

使用 Docker 和 Docker Compose 启动：

```sh
docker compose up --build -d
```

API 仅监听本机 `127.0.0.1:8000`，Redis 不发布宿主机端口。

```sh
curl -X PUT http://127.0.0.1:8000/values/1 \
  -H 'Content-Type: application/json' -d '{"value":"你好"}'
curl http://127.0.0.1:8000/values/1
```

两者返回 `{"key":1,"value":"你好"}`。键为无前导零的正整数，最大为 9223372036854775807；值为字符串，允许空字符串，UTF-8 编码最多 1 MiB。未找到返回 404，值过大返回 413，非法输入返回 422，Redis 不可用返回 503。重复写入会覆盖；并发写入以 Redis 最后处理的写入为准。

数据默认不过期，Redis 使用 AOF 每秒同步并保存到 Docker 卷；异常断电可能丢失最近约一秒的数据。`docker compose down` 停止服务并保留卷；不要使用 `down -v`，除非有意删除数据。

启动后安装测试依赖并运行测试：

```sh
python3 -m pip install -r requirements-dev.txt
python3 -m unittest discover -s tests -v
```
