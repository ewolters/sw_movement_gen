"""
CSV-based logging service for audit trail and compliance.

Logs are stored as daily CSV files that can be opened directly in Excel.
Format: outputs/logs/YYYY-MM-DD_activity.csv
"""

import csv
import os
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict
from dataclasses import dataclass
from enum import Enum


class LogEventType(Enum):
    FILE_PROCESS = "FILE"
    JOB_CREATED = "JOB"
    MOVEMENT_CREATED = "MOVEMENT"
    ALERT = "ALERT"
    SQL_QUERY = "SQL"
    ERROR = "ERROR"
    USER_ACTION = "USER"
    SYSTEM = "SYSTEM"


@dataclass
class LogEntry:
    timestamp: datetime
    event_type: LogEventType
    message: str
    details: Optional[str] = None
    part_number: Optional[str] = None
    quantity: Optional[int] = None
    po_number: Optional[str] = None
    xml_file: Optional[str] = None

    def to_row(self) -> List[str]:
        return [
            self.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
            self.event_type.value,
            self.message,
            self.details or "",
            self.part_number or "",
            str(self.quantity) if self.quantity else "",
            self.po_number or "",
            self.xml_file or ""
        ]

    @staticmethod
    def header() -> List[str]:
        return ["Timestamp", "Type", "Message", "Details", "Part Number", "Quantity", "PO Number", "XML File"]


class ActivityLogger:
    """File-based activity logger for compliance and audit trail"""

    def __init__(self, log_dir: str = "outputs/logs"):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self._entries_cache: List[LogEntry] = []  # In-memory cache for current session

    def _get_log_file(self, date: Optional[datetime] = None) -> Path:
        """Get log file path for a specific date"""
        if date is None:
            date = datetime.now()
        filename = f"{date.strftime('%Y-%m-%d')}_activity.csv"
        return self.log_dir / filename

    def _ensure_header(self, file_path: Path):
        """Ensure log file has header row"""
        if not file_path.exists():
            with open(file_path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(LogEntry.header())

    def log(self, entry: LogEntry):
        """Write a log entry to today's file"""
        file_path = self._get_log_file()
        self._ensure_header(file_path)

        with open(file_path, 'a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(entry.to_row())

        self._entries_cache.append(entry)

    def log_file_processed(self, filename: str, records: int, errors: int = 0):
        """Log file processing event"""
        status = "success" if errors == 0 else f"{errors} errors"
        self.log(LogEntry(
            timestamp=datetime.now(),
            event_type=LogEventType.FILE_PROCESS,
            message=f"Processed file: {filename}",
            details=f"{records} records, {status}"
        ))

    def log_job_created(self, job_type: str, part_number: str, quantity: int, xml_file: str, po_number: str = None):
        """Log job creation event"""
        self.log(LogEntry(
            timestamp=datetime.now(),
            event_type=LogEventType.JOB_CREATED,
            message=f"{job_type} job created: {part_number}",
            details=f"Qty: {quantity}",
            part_number=part_number,
            quantity=quantity,
            po_number=po_number,
            xml_file=xml_file
        ))

    def log_movement_created(self, part_number: str, quantity: int, xml_file: str, po_number: str = None):
        """Log stock movement creation"""
        self.log(LogEntry(
            timestamp=datetime.now(),
            event_type=LogEventType.MOVEMENT_CREATED,
            message=f"Movement created: {part_number}",
            details=f"Qty: {quantity}",
            part_number=part_number,
            quantity=quantity,
            po_number=po_number,
            xml_file=xml_file
        ))

    def log_alert(self, alert_type: str, part_number: str, message: str, details: str = None):
        """Log an alert"""
        self.log(LogEntry(
            timestamp=datetime.now(),
            event_type=LogEventType.ALERT,
            message=f"{alert_type}: {message}",
            details=details,
            part_number=part_number
        ))

    def log_sql_query(self, query: str, execution_time: float, row_count: int, error: str = None):
        """Log SQL query execution"""
        status = f"{row_count} rows in {execution_time:.2f}s" if not error else f"Error: {error}"
        self.log(LogEntry(
            timestamp=datetime.now(),
            event_type=LogEventType.SQL_QUERY,
            message="Query executed",
            details=f"{status} - {query[:100]}..."
        ))

    def log_error(self, error_type: str, message: str, details: str = None):
        """Log an error"""
        self.log(LogEntry(
            timestamp=datetime.now(),
            event_type=LogEventType.ERROR,
            message=f"{error_type}: {message}",
            details=details
        ))

    def log_user_action(self, action: str, details: str = None):
        """Log user action"""
        self.log(LogEntry(
            timestamp=datetime.now(),
            event_type=LogEventType.USER_ACTION,
            message=action,
            details=details
        ))

    def get_entries_for_date(self, date: datetime) -> List[LogEntry]:
        """Read all entries for a specific date"""
        file_path = self._get_log_file(date)
        entries = []

        if not file_path.exists():
            return entries

        with open(file_path, 'r', newline='', encoding='utf-8') as f:
            reader = csv.reader(f)
            next(reader)  # Skip header
            for row in reader:
                if len(row) >= 8:
                    entries.append(LogEntry(
                        timestamp=datetime.strptime(row[0], "%Y-%m-%d %H:%M:%S"),
                        event_type=LogEventType(row[1]),
                        message=row[2],
                        details=row[3] or None,
                        part_number=row[4] or None,
                        quantity=int(row[5]) if row[5] else None,
                        po_number=row[6] or None,
                        xml_file=row[7] or None
                    ))
        return entries

    def get_today_entries(self) -> List[LogEntry]:
        """Get all entries for today"""
        return self.get_entries_for_date(datetime.now())

    def get_today_summary(self) -> Dict[str, int]:
        """Get summary counts for today"""
        entries = self.get_today_entries()
        summary = {
            "stock_jobs": 0,
            "rush_jobs": 0,
            "movements": 0,
            "alerts": 0,
            "errors": 0
        }
        for entry in entries:
            if entry.event_type == LogEventType.JOB_CREATED:
                if "Rush" in entry.message:
                    summary["rush_jobs"] += 1
                else:
                    summary["stock_jobs"] += 1
            elif entry.event_type == LogEventType.MOVEMENT_CREATED:
                summary["movements"] += 1
            elif entry.event_type == LogEventType.ALERT:
                summary["alerts"] += 1
            elif entry.event_type == LogEventType.ERROR:
                summary["errors"] += 1
        return summary

    def get_available_dates(self) -> List[str]:
        """Get list of dates that have log files"""
        dates = []
        for f in self.log_dir.glob("*_activity.csv"):
            date_str = f.stem.replace("_activity", "")
            dates.append(date_str)
        return sorted(dates, reverse=True)


# Global logger instance
_logger: Optional[ActivityLogger] = None


def get_logger() -> ActivityLogger:
    """Get the global logger instance"""
    global _logger
    if _logger is None:
        _logger = ActivityLogger()
    return _logger
