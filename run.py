"""
Run the MCC Packaging Middleware application

Local machine only - binds to 127.0.0.1 (localhost)
Includes scheduler for daily processing with retry logic
"""
import os
import sys
import threading
import time
from datetime import datetime, timedelta
import webbrowser

# Add project to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.main import app, process_hot_folder, check_retry_needed, execute_retry
from app.services.logger import get_logger
from app.services.config import get_config


class DailyScheduler:
    """Scheduler for daily tasks with retry logic"""

    def __init__(self):
        self.running = False
        self.thread = None
        self.last_run_date = None
        self.retry_scheduled_time = None

    def _get_config_time(self):
        """Get scheduled time from config"""
        config = get_config().config
        return config.scheduler_hour, config.scheduler_minute

    def _get_next_run_time(self):
        """Calculate next run time based on config"""
        hour, minute = self._get_config_time()
        now = datetime.now()
        target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)

        # If we've already passed today's target time, schedule for tomorrow
        if now >= target:
            target += timedelta(days=1)

        return target

    def _scheduler_loop(self):
        """Main scheduler loop"""
        logger = get_logger()
        hour, minute = self._get_config_time()
        logger.log_user_action("Scheduler started", f"Daily run at {hour:02d}:{minute:02d}")

        while self.running:
            now = datetime.now()
            today = now.date()
            hour, minute = self._get_config_time()

            # Check if it's time for scheduled run
            if (now.hour == hour and
                now.minute == minute and
                self.last_run_date != today):

                print(f"\n[SCHEDULER] Running daily task at {now.strftime('%Y-%m-%d %H:%M:%S')}")
                logger.log_user_action("Scheduled daily run", f"Started at {now.strftime('%H:%M:%S')}")

                try:
                    result = process_hot_folder(is_retry=False)
                    self.last_run_date = today

                    # Check if retry was scheduled (empty folder)
                    if check_retry_needed():
                        self.retry_scheduled_time = now + timedelta(hours=1)
                        print(f"[SCHEDULER] Retry scheduled for {self.retry_scheduled_time.strftime('%H:%M:%S')}")

                    logger.log_user_action("Scheduled daily run completed", result)
                except Exception as e:
                    logger.log_error("Scheduler", f"Daily run failed: {str(e)}")
                    print(f"[SCHEDULER] Error: {e}")

            # Check if retry is due
            if self.retry_scheduled_time and now >= self.retry_scheduled_time:
                print(f"\n[SCHEDULER] Running retry at {now.strftime('%Y-%m-%d %H:%M:%S')}")

                try:
                    result = execute_retry()
                    self.retry_scheduled_time = None
                    logger.log_user_action("Retry completed", result)
                except Exception as e:
                    logger.log_error("Scheduler", f"Retry failed: {str(e)}")
                    print(f"[SCHEDULER] Retry error: {e}")
                    self.retry_scheduled_time = None

            # Sleep for 30 seconds before checking again
            time.sleep(30)

    def start(self):
        """Start the scheduler in a background thread"""
        if self.running:
            return

        self.running = True
        self.thread = threading.Thread(target=self._scheduler_loop, daemon=True)
        self.thread.start()

        next_run = self._get_next_run_time()
        print(f"[SCHEDULER] Started - next run at {next_run.strftime('%Y-%m-%d %H:%M:%S')}")

    def stop(self):
        """Stop the scheduler"""
        self.running = False
        if self.thread:
            self.thread.join(timeout=5)


def open_browser():
    """Open browser after short delay"""
    time.sleep(1.5)
    webbrowser.open('http://127.0.0.1:5000')


if __name__ == '__main__':
    config = get_config().config

    print("=" * 60)
    print("MCC Packaging Automation Middleware")
    print("=" * 60)
    print("")
    print("LOCAL MACHINE ONLY - Not accessible from network")
    print("")
    print("Server: http://127.0.0.1:5000")
    print(f"Scheduler: Daily at {config.scheduler_hour:02d}:{config.scheduler_minute:02d}")
    print("")
    print("Press Ctrl+C to stop")
    print("=" * 60)

    # Start scheduler
    scheduler = DailyScheduler()
    scheduler.start()

    # Open browser automatically
    threading.Thread(target=open_browser, daemon=True).start()

    try:
        # Run Flask - localhost only (127.0.0.1), not network accessible
        app.run(
            debug=False,  # Disable debug for production-like local use
            host='127.0.0.1',  # Localhost only - NOT accessible from network
            port=5000,
            threaded=True,
            use_reloader=False  # Disable reloader to prevent scheduler duplication
        )
    except KeyboardInterrupt:
        print("\nShutting down...")
        scheduler.stop()
