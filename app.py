"""Local HTTP key-value service backed by Redis."""
import os
import re
from contextlib import asynccontextmanager

import redis.asyncio as redis
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, StrictStr
from redis.exceptions import RedisError

MAX_KEY = 9223372036854775807
MAX_VALUE_BYTES = 1024 * 1024


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.redis = redis.from_url(os.getenv("REDIS_URL", "redis://redis:6379/0"), decode_responses=True)
    yield
    await app.state.redis.aclose()


app = FastAPI(lifespan=lifespan)


class ValueInput(BaseModel):
    value: StrictStr


def parse_key(key: str) -> int:
    if not re.fullmatch(r"[1-9][0-9]{0,18}", key) or int(key) > MAX_KEY:
        raise HTTPException(status_code=422, detail="Key must be a canonical positive 64-bit integer")
    return int(key)


@app.put("/values/{key}")
async def put_value(key: str, payload: ValueInput):
    number = parse_key(key)
    if len(payload.value.encode("utf-8")) > MAX_VALUE_BYTES:
        raise HTTPException(status_code=413, detail="Value exceeds 1 MiB in UTF-8")
    try:
        await app.state.redis.set(str(number), payload.value)
    except RedisError as exc:
        raise HTTPException(status_code=503, detail="Redis unavailable") from exc
    return {"key": number, "value": payload.value}


@app.get("/values/{key}")
async def get_value(key: str):
    number = parse_key(key)
    try:
        value = await app.state.redis.get(str(number))
    except RedisError as exc:
        raise HTTPException(status_code=503, detail="Redis unavailable") from exc
    if value is None:
        raise HTTPException(status_code=404, detail="Key not found")
    return {"key": number, "value": value}
