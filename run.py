import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from tracker import create_app
from tracker.services.scheduler import start_scheduler

app = create_app()

if __name__ == "__main__":
    start_scheduler()
    host = os.environ.get("TRACKER_HOST", "127.0.0.1")
    port = int(os.environ.get("TRACKER_PORT", "8000"))
    print(f"Tracker Kanban -> http://{host}:{port}")
    app.run(host=host, port=port, threaded=True, debug=False)
