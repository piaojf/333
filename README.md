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

### 验证 Redis 持久化

持久化测试会重启并重新创建 Redis 容器。请只对专门的测试项目运行，避免影响已有服务和数据；测试项目名称必须以 `persistence-test-` 开头。下面的命令使用独立卷，API 默认占用本机 8000 端口：

```sh
export PERSISTENCE_TEST_PROJECT=persistence-test-local
docker compose -p "$PERSISTENCE_TEST_PROJECT" up --build -d
python3 -m unittest discover -s tests -p test_persistence.py -v
docker compose -p "$PERSISTENCE_TEST_PROJECT" down
```

`down` 保留测试卷。测试从目标 Compose 项目获取 API 端口，通过 HTTP 写入值，并在 Redis 重启和保留卷重建后分别读取；测试不会模拟异常断电。日常运行完整测试时未设置 `PERSISTENCE_TEST_PROJECT` 会跳过该测试。

### 验证 Redis 故障与并发写入

以下测试需要本机的 `redis-server` 和 `redis-cli`。它会在临时目录和随机本机端口启动专用 Redis 与 API 进程，测试结束后关闭进程并清理临时数据，不会停止已有的 Redis。Redis 的 `MONITOR` 会记录测试命令和值。

```sh
export REDIS_TEST_SERVER="$(command -v redis-server)"
export REDIS_TEST_CLI="$(command -v redis-cli)"
python3 -m unittest discover -s tests -p test_redis_behavior.py -v
```

测试检查 Redis 停止时读写返回 503，恢复后原值仍在；并发测试根据 Redis `MONITOR` 记录的 SET 命令顺序确定最后处理的写入，再通过 API 读取并比较最终值。未设置两个 Redis 可执行文件路径时测试会跳过。
