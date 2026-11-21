from django.http import FileResponse, Http404, JsonResponse
from django.urls import path
from django.conf import settings
from planner.views import plan


def index(request):
    index_file = settings.BASE_DIR / "frontend" / "dist" / "index.html"
    if not index_file.exists():
        raise Http404("Build the frontend first, or run the Vite development server.")
    return FileResponse(index_file.open("rb"), content_type="text/html")


def health(request):
    return JsonResponse({"status": "ok"})


urlpatterns = [path("", index), path("api/plan", plan), path("api/health", health)]
