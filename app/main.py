import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

# passlib 1.7.4 genera un warning inofensivo con bcrypt >=4.1; lo bajamos a ERROR.
logging.getLogger("passlib.handlers.bcrypt").setLevel(logging.ERROR)
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.config import settings
from app.db.base import Base, engine
from app.api import auth, chat, eventos
from app.servicios.scheduler import start_scheduler, stop_scheduler

MAIN_LOOP: asyncio.AbstractEventLoop | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global MAIN_LOOP
    Base.metadata.create_all(bind=engine)
    MAIN_LOOP = asyncio.get_event_loop()
    start_scheduler(MAIN_LOOP)
    yield
    stop_scheduler()


app = FastAPI(title="Trackr", lifespan=lifespan)
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.SECRET_KEY,
    max_age=3600 * 24 * 7,
)

app.include_router(auth.router)
app.include_router(chat.router)
app.include_router(eventos.router)

app.mount("/", StaticFiles(directory="app/static", html=True), name="static")
