from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app import seed
from app.modules.空窗发射策略 import 策略未定错误
from app.modules.空窗策略戳 import 空窗策略戳错误
from app.routers import api

app = FastAPI(title="播浪", version="0.1.0")
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)


@app.exception_handler(策略未定错误)
def _策略未定拒载(_: Request, exc: 策略未定错误):

    return JSONResponse(status_code=409, content={"错误类型": "空窗策略未定", "说明": str(exc)})


@app.exception_handler(空窗策略戳错误)
def _策略戳漂移拒载(_: Request, exc: 空窗策略戳错误):
    # 戳漂移 fail-closed：补扫/装载整票回滚，返回 409 供调用方识别。
    return JSONResponse(status_code=409, content={"错误类型": "空窗策略戳漂移", "说明": str(exc)})


@app.on_event("startup")
def _启动():
    seed.初始化库()


app.include_router(api)
