import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.routes import chat_router, health_router, recommendations_router, saved_movies_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s - %(message)s",
)

app = FastAPI(
    title="CineMatch AI Backend",
    version="0.1.0",
    description="Mock-ready FastAPI backend for the CineMatch AI Expo app.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(chat_router)
app.include_router(recommendations_router)
app.include_router(saved_movies_router)
