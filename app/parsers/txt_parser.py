"""
TXT Parser for Sherwin-Williams Purchase Order Files

Parses fixed-width format files with Header (H) and Detail (D) records.

File format:
- Header (H): Site(4) + PO#(6) + 'H' + Date(6) + legacy fields (ignored)
- Detail (D): Site(4) + PO#(6) + 'D' + Line#(3) + PartNum(~18) + Qty + 'EA' + Price + DueDate + legacy

Example Header: 45FL907465H111925CLFDB
Example Detail: 45FL907465D  1L-61370444-14        5500EA00000.1269011/19/2025  A
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional, Tuple
from pathlib import Path
import re


@dataclass
class POHeader:
    """Purchase Order Header record"""
    site_code: str
    po_number: str
    date: datetime
    raw_line: str = ""

    def __str__(self):
        return f"PO {self.po_number} @ {self.site_code} ({self.date.strftime('%m/%d/%Y')})"


@dataclass
class PODetail:
    """Purchase Order Detail/Line record"""
    site_code: str
    po_number: str
    line_number: int
    part_number: str
    quantity: int
    unit_price: float
    due_date: datetime
    uom: str = "EA"
    raw_line: str = ""

    # Reference to parent header (set after parsing)
    header: Optional[POHeader] = field(default=None, repr=False)

    def __str__(self):
        return f"Line {self.line_number}: {self.part_number} x {self.quantity} (due {self.due_date.strftime('%m/%d/%Y')})"

    @property
    def quantity_rounded(self) -> int:
        """Quantity rounded UP to nearest 500 (pack size)"""
        import math
        return math.ceil(self.quantity / 500) * 500


@dataclass
class PurchaseOrder:
    """Complete Purchase Order with header and detail lines"""
    header: POHeader
    details: List[PODetail] = field(default_factory=list)

    def __str__(self):
        return f"{self.header} - {len(self.details)} line(s)"

    @property
    def total_quantity(self) -> int:
        return sum(d.quantity for d in self.details)


def parse_header_line(line: str) -> Optional[POHeader]:
    """
    Parse a header (H) line.

    Format: Site(4) + PO#(6) + 'H' + Date(6:MMDDYY) + rest ignored
    Example: 45FL907465H111925CLFDB
    """
    line = line.rstrip()
    if len(line) < 17:
        return None

    # Check for 'H' at position 10 (0-indexed)
    if len(line) > 10 and line[10] != 'H':
        return None

    try:
        site_code = line[0:4]
        po_number = line[4:10]
        date_str = line[11:17]  # MMDDYY

        # Parse date (MMDDYY format)
        month = int(date_str[0:2])
        day = int(date_str[2:4])
        year = int(date_str[4:6])
        # Assume 2000s for 2-digit year
        year = 2000 + year if year < 50 else 1900 + year

        date = datetime(year, month, day)

        return POHeader(
            site_code=site_code,
            po_number=po_number,
            date=date,
            raw_line=line
        )
    except (ValueError, IndexError) as e:
        return None


def parse_detail_line(line: str) -> Optional[PODetail]:
    """
    Parse a detail (D) line.

    Format is complex fixed-width with some variation. Key fields:
    - Site(4) + PO#(6) + 'D' + LineNum(3) + PartNum(variable) + Qty + 'EA' + Price + DueDate

    Example: 45FL907465D  1L-61370444-14        5500EA00000.1269011/19/2025  A
    """
    line = line.rstrip()
    if len(line) < 50:
        return None

    # Check for 'D' at position 10 (0-indexed)
    if len(line) > 10 and line[10] != 'D':
        return None

    try:
        site_code = line[0:4]
        po_number = line[4:10]
        line_num_str = line[11:14].strip()
        line_number = int(line_num_str) if line_num_str else 0

        # The rest of the line is trickier - part number starts at pos 14
        # and runs until we hit the quantity (which ends with 'EA')
        rest = line[14:]

        # Find 'EA' which marks end of quantity
        ea_match = re.search(r'(\d+)EA', rest)
        if not ea_match:
            return None

        ea_pos = ea_match.start()
        qty_str = ea_match.group(1)
        quantity = int(qty_str)

        # Part number is everything before the quantity digits
        # Work backwards from quantity to find where part number ends
        part_and_qty = rest[:ea_match.end()]

        # Find where the quantity starts (sequence of digits before EA)
        qty_match = re.search(r'(\d+)EA$', part_and_qty)
        if qty_match:
            part_number = part_and_qty[:qty_match.start()].strip()
        else:
            part_number = rest[:ea_pos].strip()

        # After 'EA' comes price (11 chars like 00000.12690) then date
        after_ea = rest[ea_match.end():]

        # Price is next ~11 characters (format: 00000.12690)
        price_match = re.match(r'(\d{5}\.\d{4,5})', after_ea)
        if price_match:
            unit_price = float(price_match.group(1))
            after_price = after_ea[price_match.end():]
        else:
            unit_price = 0.0
            after_price = after_ea

        # Due date follows (format: 0MM/DD/YYYY or MM/DD/YYYY)
        # Remove leading 0 if present (sometimes there's a leading 0)
        date_match = re.search(r'0?(\d{1,2}/\d{1,2}/\d{4})', after_price)
        if date_match:
            date_str = date_match.group(1)
            due_date = datetime.strptime(date_str, '%m/%d/%Y')
        else:
            due_date = datetime.now()  # fallback

        return PODetail(
            site_code=site_code,
            po_number=po_number,
            line_number=line_number,
            part_number=part_number,
            quantity=quantity,
            unit_price=unit_price,
            due_date=due_date,
            raw_line=line
        )
    except (ValueError, IndexError) as e:
        return None


def parse_po_file(file_path: str) -> Tuple[List[PurchaseOrder], List[str]]:
    """
    Parse a complete PO file and return list of PurchaseOrders.

    Args:
        file_path: Path to the .txt PO file

    Returns:
        Tuple of (list of PurchaseOrders, list of error messages)
    """
    purchase_orders: List[PurchaseOrder] = []
    errors: List[str] = []

    current_header: Optional[POHeader] = None
    current_details: List[PODetail] = []

    path = Path(file_path)
    if not path.exists():
        return [], [f"File not found: {file_path}"]

    with open(path, 'r', encoding='utf-8', errors='ignore') as f:
        for line_num, line in enumerate(f, 1):
            line = line.rstrip()
            if not line:
                continue

            # Determine record type by character at position 10
            if len(line) > 10:
                record_type = line[10]
            else:
                errors.append(f"Line {line_num}: Too short to parse")
                continue

            if record_type == 'H':
                # Save previous PO if exists
                if current_header and current_details:
                    po = PurchaseOrder(header=current_header, details=current_details)
                    purchase_orders.append(po)

                # Start new PO
                header = parse_header_line(line)
                if header:
                    current_header = header
                    current_details = []
                else:
                    errors.append(f"Line {line_num}: Failed to parse header")

            elif record_type == 'D':
                detail = parse_detail_line(line)
                if detail:
                    if current_header:
                        detail.header = current_header
                    current_details.append(detail)
                else:
                    errors.append(f"Line {line_num}: Failed to parse detail")
            else:
                errors.append(f"Line {line_num}: Unknown record type '{record_type}'")

    # Don't forget the last PO
    if current_header and current_details:
        po = PurchaseOrder(header=current_header, details=current_details)
        purchase_orders.append(po)

    return purchase_orders, errors


def get_all_details(purchase_orders: List[PurchaseOrder]) -> List[PODetail]:
    """Flatten all details from all POs into a single list"""
    details = []
    for po in purchase_orders:
        details.extend(po.details)
    return details


def get_unique_parts(purchase_orders: List[PurchaseOrder]) -> List[str]:
    """Get list of unique part numbers from all POs"""
    parts = set()
    for po in purchase_orders:
        for detail in po.details:
            parts.add(detail.part_number)
    return sorted(parts)


# CLI testing
if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        file_path = sys.argv[1]
    else:
        file_path = "inputs/qadp0961_7360_251030070105.txt"

    print(f"Parsing: {file_path}")
    print("-" * 60)

    pos, errors = parse_po_file(file_path)

    print(f"Found {len(pos)} Purchase Orders")
    print(f"Errors: {len(errors)}")

    if errors:
        print("\nFirst 5 errors:")
        for e in errors[:5]:
            print(f"  {e}")

    print("\nFirst 5 POs:")
    for po in pos[:5]:
        print(f"\n{po}")
        for detail in po.details[:3]:
            print(f"  {detail}")
        if len(po.details) > 3:
            print(f"  ... and {len(po.details) - 3} more lines")

    all_details = get_all_details(pos)
    unique_parts = get_unique_parts(pos)

    print(f"\nTotal: {len(all_details)} line items, {len(unique_parts)} unique parts")
