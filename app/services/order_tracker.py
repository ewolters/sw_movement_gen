"""
Order Tracker Service

Tracks cumulative orders by part + site + month for forecast comparison.
Stored in CSV format: outputs/orders/YYYY-MM_orders.csv

This allows comparison of total monthly orders against monthly forecast.
"""

import csv
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass


@dataclass
class OrderRecord:
    """Single order record"""
    timestamp: datetime
    po_number: str
    part_number: str
    site: str
    quantity: int
    quantity_rounded: int  # Rounded to pack size (500)

    def to_row(self) -> List[str]:
        return [
            self.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
            self.po_number,
            self.part_number,
            self.site,
            str(self.quantity),
            str(self.quantity_rounded)
        ]

    @staticmethod
    def header() -> List[str]:
        return ["Timestamp", "PO Number", "Part Number", "Site", "Quantity", "Quantity Rounded"]


class OrderTracker:
    """
    Tracks all orders by month for cumulative comparison against forecast.

    Each month gets its own CSV file for easy auditing.
    """

    def __init__(self, orders_dir: str = "outputs/orders"):
        self.orders_dir = Path(orders_dir)
        self.orders_dir.mkdir(parents=True, exist_ok=True)

    def _get_month_file(self, year: int, month: int) -> Path:
        """Get orders file for specific month"""
        return self.orders_dir / f"{year}-{month:02d}_orders.csv"

    def _ensure_header(self, file_path: Path):
        """Ensure file has header row"""
        if not file_path.exists():
            with open(file_path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(OrderRecord.header())

    def record_order(self, po_number: str, part_number: str, site: str,
                     quantity: int, quantity_rounded: int,
                     timestamp: Optional[datetime] = None):
        """
        Record an order for tracking.

        This should be called when a PO is processed, for each line item.
        """
        if timestamp is None:
            timestamp = datetime.now()

        record = OrderRecord(
            timestamp=timestamp,
            po_number=po_number,
            part_number=part_number,
            site=str(site),
            quantity=quantity,
            quantity_rounded=quantity_rounded
        )

        file_path = self._get_month_file(timestamp.year, timestamp.month)
        self._ensure_header(file_path)

        with open(file_path, 'a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(record.to_row())

    def get_monthly_orders(self, year: int, month: int) -> List[OrderRecord]:
        """Get all orders for a specific month"""
        file_path = self._get_month_file(year, month)
        records = []

        if not file_path.exists():
            return records

        with open(file_path, 'r', newline='', encoding='utf-8') as f:
            reader = csv.reader(f)
            next(reader)  # Skip header
            for row in reader:
                if len(row) >= 6:
                    records.append(OrderRecord(
                        timestamp=datetime.strptime(row[0], "%Y-%m-%d %H:%M:%S"),
                        po_number=row[1],
                        part_number=row[2],
                        site=row[3],
                        quantity=int(row[4]),
                        quantity_rounded=int(row[5])
                    ))
        return records

    def get_cumulative_by_part_site(self, year: int, month: int,
                                     part_number: str, site: str) -> Tuple[int, int]:
        """
        Get cumulative order totals for a specific part at a site for the month.

        Returns:
            Tuple of (total_quantity, total_quantity_rounded)
        """
        records = self.get_monthly_orders(year, month)
        site_str = str(site)

        total_qty = 0
        total_rounded = 0

        for r in records:
            if r.part_number == part_number and r.site == site_str:
                total_qty += r.quantity
                total_rounded += r.quantity_rounded

        return total_qty, total_rounded

    def get_cumulative_by_part(self, year: int, month: int,
                                part_number: str) -> Tuple[int, int]:
        """
        Get cumulative order totals for a part across ALL sites for the month.

        Returns:
            Tuple of (total_quantity, total_quantity_rounded)
        """
        records = self.get_monthly_orders(year, month)

        total_qty = 0
        total_rounded = 0

        for r in records:
            if r.part_number == part_number:
                total_qty += r.quantity
                total_rounded += r.quantity_rounded

        return total_qty, total_rounded

    def get_month_summary(self, year: int, month: int) -> Dict[str, Dict[str, int]]:
        """
        Get summary of all orders for a month, grouped by part+site.

        Returns:
            Dict with keys like "PART|SITE" -> {"quantity": X, "rounded": Y, "count": Z}
        """
        records = self.get_monthly_orders(year, month)
        summary = {}

        for r in records:
            key = f"{r.part_number}|{r.site}"
            if key not in summary:
                summary[key] = {"quantity": 0, "rounded": 0, "count": 0}
            summary[key]["quantity"] += r.quantity
            summary[key]["rounded"] += r.quantity_rounded
            summary[key]["count"] += 1

        return summary

    def get_current_month_cumulative(self, part_number: str, site: str) -> Tuple[int, int]:
        """Convenience method to get current month's cumulative for a part+site"""
        now = datetime.now()
        return self.get_cumulative_by_part_site(now.year, now.month, part_number, site)

    def is_po_already_recorded(self, po_number: str, year: int = None, month: int = None) -> bool:
        """
        Check if a PO has already been recorded (to prevent double-counting).

        If year/month not provided, checks current month.
        """
        if year is None or month is None:
            now = datetime.now()
            year = now.year
            month = now.month

        records = self.get_monthly_orders(year, month)
        return any(r.po_number == po_number for r in records)

    def get_recorded_pos(self, year: int = None, month: int = None) -> List[str]:
        """Get list of PO numbers already recorded for the month"""
        if year is None or month is None:
            now = datetime.now()
            year = now.year
            month = now.month

        records = self.get_monthly_orders(year, month)
        return list(set(r.po_number for r in records))


# Global tracker instance
_tracker: Optional[OrderTracker] = None


def get_order_tracker() -> OrderTracker:
    """Get the global order tracker instance"""
    global _tracker
    if _tracker is None:
        _tracker = OrderTracker()
    return _tracker
