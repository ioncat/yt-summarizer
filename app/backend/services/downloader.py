"""Downloading a video or its audio with yt-dlp (the browser download buttons and the queue's download stage)."""
from __future__ import annotations


def mp4_format_spec(quality: str) -> str:
    if quality == "best":
        return "bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best"
    h = quality.rstrip("p")
    return (
        f"bestvideo[height<={h}][ext=mp4]+bestaudio[ext=m4a]"
        f"/bestvideo[height<={h}]+bestaudio/best[height<={h}]"
    )
