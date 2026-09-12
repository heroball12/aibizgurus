"""Enable the landing film only when the finished, reviewed assets are shipped."""
from django.contrib.staticfiles import finders


def landing_film_assets():
    video = "video/ai-arrival.mp4"
    captions = "video/ai-arrival.vtt"
    return {
        "video": video if finders.find(video) else "",
        "captions": captions if finders.find(captions) else "",
    }
