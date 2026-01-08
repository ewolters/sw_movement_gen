"""
XML Generator Service for Sherwin-Williams Packaging Automation

Generates two types of XML output:
1. Stock Jobs (sw-stock-MMDDYY#.xml) - New production from forecast
2. Stock Movements (GT-Movement-MMDDYY-HHMMSS-###.xml) - Pull from inventory

DTD: http://www.fortdearborn.com/dtd/order-entry_1_1.dtd
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional, Tuple
import math
import xml.etree.ElementTree as ET
from xml.dom import minidom


# Constants
DTD_URL = "http://www.fortdearborn.com/dtd/order-entry_1_1.dtd"
PLANT = "14"
CUSTOMER_CODE = "SHER003"
BASE_ADDRESS = "12977"
DELIVERY_METHOD = "TRK"


@dataclass
class StockJobLine:
    """Single line item for a stock job"""
    part_number: str  # customer-reference-number
    quantity: int  # Will be rounded to 500
    price: float = 100.00
    price_qty: int = 1000

    @property
    def quantity_rounded(self) -> int:
        """Round UP to nearest 500"""
        return math.ceil(self.quantity / 500) * 500


@dataclass
class StockJob:
    """Stock job order (from forecast)"""
    lines: List[StockJobLine]
    delivery_address: str = "13316"
    delivery_date: Optional[datetime] = None
    po_received_date: Optional[datetime] = None

    def __post_init__(self):
        if self.delivery_date is None:
            self.delivery_date = datetime.now() + timedelta(days=21)
        if self.po_received_date is None:
            self.po_received_date = datetime.now()


@dataclass
class MovementLine:
    """Single line item for a stock movement"""
    item_code: str  # Internal item code from DB
    job_number: str  # Existing job to pull from
    quantity: int  # Exact quantity (no rounding)
    price: float = 50.00
    price_qty: int = 1000
    use_wip: bool = False  # True for fail-if-insufficient-wip


@dataclass
class StockMovement:
    """Stock movement order (pull from inventory)"""
    po_number: str  # Original PO number
    lines: List[MovementLine]
    delivery_address: str = "16291"
    delivery_date: Optional[datetime] = None
    po_received_date: Optional[datetime] = None
    crif_date: Optional[datetime] = None

    def __post_init__(self):
        if self.delivery_date is None:
            self.delivery_date = datetime.now()
        if self.po_received_date is None:
            self.po_received_date = datetime.now()
        if self.crif_date is None:
            self.crif_date = datetime.now()


def _prettify_xml(elem: ET.Element) -> str:
    """Return a pretty-printed XML string with proper formatting"""
    rough_string = ET.tostring(elem, encoding='unicode')
    reparsed = minidom.parseString(rough_string)

    # Get pretty printed version
    pretty = reparsed.toprettyxml(indent="   ")

    # Remove extra blank lines and fix formatting
    lines = []
    for line in pretty.split('\n'):
        stripped = line.rstrip()
        if stripped:  # Skip empty lines
            lines.append(stripped)

    return '\n'.join(lines)


def _format_date_short(dt: datetime) -> str:
    """Format date as M/D/YYYY (no leading zeros)"""
    return f"{dt.month}/{dt.day}/{dt.year}"


def _format_date_long(dt: datetime) -> str:
    """Format date as MM/DD/YYYY"""
    return dt.strftime("%m/%d/%Y")


def generate_stock_job_xml(
    jobs: List[StockJob],
    output_dir: str,
    sequence_start: int = 101
) -> Tuple[str, int]:
    """
    Generate stock job XML file.

    Args:
        jobs: List of StockJob objects to include
        output_dir: Directory to save the XML file
        sequence_start: Starting sequence number for PO generation

    Returns:
        Tuple of (filepath, order_count)
    """
    now = datetime.now()
    date_str = now.strftime("%m%d%y")

    # Find next available filename
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    suffix = 'a'
    while True:
        filename = f"sw-stock-{date_str}{suffix}.xml"
        filepath = output_path / filename
        if not filepath.exists():
            break
        suffix = chr(ord(suffix) + 1)
        if suffix > 'z':
            suffix = 'aa'

    # Build XML
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<!DOCTYPE orders SYSTEM "{DTD_URL}">',
        '',
        '<!--Generated from customer order entry -->',
        '',
        '<orders>'
    ]

    po_sequence = sequence_start
    order_count = 0

    for job in jobs:
        for line in job.lines:
            po_num = f"VMI {now.strftime('%m.%d.%y')} {po_sequence}"
            delivery_date = _format_date_short(job.delivery_date)
            po_received = _format_date_long(job.po_received_date)
            crif = _format_date_short(job.delivery_date)

            # Match exact schema from sample: address before code in order-customer
            order_xml = f'''<order signal="submit" plant="{PLANT}">
   <header>
      <order-customer address="{BASE_ADDRESS}" code="{CUSTOMER_CODE}">
         <po>{po_num}</po>
      </order-customer>
      <invoice-customer address="{BASE_ADDRESS}"/>
      <delivery-customer address="{job.delivery_address}" date="{delivery_date}">
         <delivery-method code="{DELIVERY_METHOD}">
            <freight>
               <prepaid />
            </freight>
         </delivery-method>
      </delivery-customer>
    <request-options po-received="{po_received}" crif="{crif}" crif-ship="{crif}" />
   </header>
   <lines>
      <line quantity="{line.quantity_rounded}" run-type="normal">
         <option>
          <book-stock-job price="{line.price:.2f}" price-qty="{line.price_qty}" />
         </option>
         <item>
            <customer-reference-number>{line.part_number}</customer-reference-number>
         </item>
      </line>
   </lines>
</order>'''
            lines.append(order_xml)
            po_sequence += 1
            order_count += 1

    lines.append('</orders>')

    # Write file
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))

    return str(filepath), order_count


def generate_movement_xml(
    movements: List[StockMovement],
    output_dir: str
) -> Tuple[str, int]:
    """
    Generate stock movement XML file.

    Args:
        movements: List of StockMovement objects to include
        output_dir: Directory to save the XML file

    Returns:
        Tuple of (filepath, order_count)
    """
    now = datetime.now()
    date_str = now.strftime("%m%d%y")
    time_str = now.strftime("%H%M%S")

    # Find next available filename
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    seq = 1
    while True:
        filename = f"GT-Movement-{date_str}-{time_str}-{seq:03d}.xml"
        filepath = output_path / filename
        if not filepath.exists():
            break
        seq += 1

    # Build XML
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<!DOCTYPE orders SYSTEM "{DTD_URL}">',
        '',
        '<!--Generated from S-W Order Entry Interface -->',
        '',
        '<orders>'
    ]

    order_count = 0

    for movement in movements:
        ro_sequence = 1

        for line in movement.lines:
            delivery_date = _format_date_long(movement.delivery_date)
            po_received = _format_date_long(movement.po_received_date)
            crif = _format_date_long(movement.crif_date)

            # Choose option type based on WIP flag
            if line.use_wip:
                option_tag = f'<fail-if-insufficient-wip job-number="{line.job_number}" price="{int(line.price)}" price-qty="{line.price_qty}" />'
            else:
                option_tag = f'<fail-if-insufficient-stock job-number="{line.job_number}" price="{int(line.price)}" price-qty="{line.price_qty}" />'

            order_xml = f'''<order signal="submit" plant="{PLANT}">
  <header>
    <order-customer code="{CUSTOMER_CODE}" address="{BASE_ADDRESS}">
      <po>{movement.po_number}</po>
      <ro>{ro_sequence:03d}</ro>
    </order-customer>
    <invoice-customer code="{CUSTOMER_CODE}" address="{BASE_ADDRESS}"></invoice-customer>
    <delivery-customer code="{CUSTOMER_CODE}" address="{movement.delivery_address}" date="{delivery_date}">
      <delivery-method code="{DELIVERY_METHOD}">
        <freight>
           <collect />
        </freight>
      </delivery-method>
    </delivery-customer>
    <request-options po-received="{po_received}" crif="{crif}" />
  </header>
  <lines>
    <line quantity="{line.quantity}" run-type="normal">
       <option>
          {option_tag}
       </option>
    <item>
      <item-code>{line.item_code}</item-code>
    </item>
    </line>
  </lines>
</order>'''
            lines.append(order_xml)
            ro_sequence += 1
            order_count += 1

    lines.append('</orders>')

    # Write file
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))

    return str(filepath), order_count


class XMLGeneratorService:
    """Service for generating XML output files"""

    def __init__(self, default_output_dir: str = None):
        self.default_output_dir = default_output_dir or "outputs/xml"
        self._stock_job_sequence = 101

    def set_output_dir(self, path: str) -> bool:
        """Set the default output directory"""
        try:
            Path(path).mkdir(parents=True, exist_ok=True)
            self.default_output_dir = path
            return True
        except Exception:
            return False

    def generate_stock_jobs(
        self,
        jobs: List[StockJob],
        output_dir: str = None
    ) -> Tuple[str, int]:
        """
        Generate stock job XML.

        Returns:
            Tuple of (filepath, order_count)
        """
        output = output_dir or self.default_output_dir
        filepath, count = generate_stock_job_xml(
            jobs, output, self._stock_job_sequence
        )
        self._stock_job_sequence += count
        return filepath, count

    def generate_movements(
        self,
        movements: List[StockMovement],
        output_dir: str = None
    ) -> Tuple[str, int]:
        """
        Generate stock movement XML.

        Returns:
            Tuple of (filepath, order_count)
        """
        output = output_dir or self.default_output_dir
        return generate_movement_xml(movements, output)

    def reset_sequence(self, start: int = 101):
        """Reset the PO sequence number"""
        self._stock_job_sequence = start


# Singleton instance
_xml_generator = None


def get_xml_generator() -> XMLGeneratorService:
    """Get the singleton XML generator service"""
    global _xml_generator
    if _xml_generator is None:
        _xml_generator = XMLGeneratorService()
    return _xml_generator
