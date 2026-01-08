"""
SQL Execution Service

Provides functions to execute configured SQL queries against the ERP database.
Supports ODBC connections via pyodbc for SQL Server, Oracle, etc.
"""

from dataclasses import dataclass
from typing import Optional, List, Dict, Tuple, Any
from datetime import datetime

from app.services.config import get_config, SQL_QUERY_TYPES
from app.services.logger import get_logger

# Try to import pyodbc for database connectivity
try:
    import pyodbc
    PYODBC_AVAILABLE = True
except ImportError:
    PYODBC_AVAILABLE = False


@dataclass
class InventoryResult:
    """Result from inventory query"""
    item_code: str
    job_number: Optional[str]
    quantity: int
    location: Optional[str] = None


@dataclass
class JobResult:
    """Result from open jobs query"""
    job_number: str
    item_code: str
    part_number: str
    quantity_ordered: int
    quantity_produced: int
    quantity_remaining: int
    status: str


@dataclass
class MovementResult:
    """Result from movements query"""
    movement_id: str
    job_number: str
    quantity: int
    status: str
    created_date: datetime


@dataclass
class ItemMapping:
    """Result from item mapping query"""
    part_number: str
    item_code: str
    description: Optional[str] = None


class SQLExecutionError(Exception):
    """Raised when SQL execution fails"""
    pass


class SQLNotConfiguredError(Exception):
    """Raised when required SQL query is not configured"""
    pass


class SQLService:
    """
    Service for executing SQL queries against the ERP database.

    Supports ODBC connections via pyodbc. Configure credentials in the SQL Query page.
    """

    def __init__(self):
        self.config = get_config()
        self.logger = get_logger()
        self._connection = None
        self._connection_error = None

    def is_connected(self) -> bool:
        """Check if database connection is available"""
        if self._connection:
            try:
                # Test connection is still alive
                cursor = self._connection.cursor()
                cursor.execute("SELECT 1")
                cursor.close()
                return True
            except Exception:
                self._connection = None
                return False
        return False

    def get_connection_status(self) -> Dict:
        """Get detailed connection status"""
        db_config = self.config.config.db_credentials
        return {
            'connected': self.is_connected(),
            'pyodbc_available': PYODBC_AVAILABLE,
            'credentials_configured': db_config is not None and db_config.get('connection_string'),
            'error': self._connection_error
        }

    def connect(self) -> Tuple[bool, str]:
        """
        Establish database connection using configured credentials.

        Returns:
            Tuple of (success: bool, message: str)
        """
        if not PYODBC_AVAILABLE:
            self._connection_error = "pyodbc not installed. Run: pip install pyodbc"
            return False, self._connection_error

        db_config = self.config.config.db_credentials
        if not db_config or not db_config.get('connection_string'):
            self._connection_error = "Database credentials not configured"
            return False, self._connection_error

        try:
            connection_string = db_config['connection_string']
            self._connection = pyodbc.connect(connection_string, timeout=10)
            self._connection_error = None
            self.logger.log_user_action("Database connected", "Connection established")
            return True, "Connected successfully"
        except Exception as e:
            self._connection_error = str(e)
            self.logger.log_error("Database Connection", str(e))
            return False, str(e)

    def disconnect(self):
        """Close database connection"""
        if self._connection:
            try:
                self._connection.close()
            except Exception:
                pass
            self._connection = None

    def _validate_query(self, query_type: str) -> str:
        """Validate and return query, raising error if not configured"""
        query = self.config.get_sql_query(query_type)
        if not query or not query.strip():
            raise SQLNotConfiguredError(f"SQL query '{query_type}' is not configured")
        return query

    def _substitute_params(self, query: str, params: dict) -> str:
        """Substitute :param_name style parameters in query"""
        result = query
        for key, value in (params or {}).items():
            placeholder = f":{key}"
            if value is None:
                result = result.replace(placeholder, "NULL")
            elif isinstance(value, str):
                # Escape single quotes
                escaped = value.replace("'", "''")
                result = result.replace(placeholder, f"'{escaped}'")
            else:
                result = result.replace(placeholder, str(value))
        return result

    def _execute_query(self, query: str, params: dict = None) -> List[Dict]:
        """
        Execute a SQL query and return results as list of dictionaries.

        Args:
            query: SQL query with :param_name style parameters
            params: Dictionary of parameter values

        Returns:
            List of dictionaries with column names as keys
        """
        start_time = datetime.now()

        # Substitute parameters
        final_query = self._substitute_params(query, params)

        if not self.is_connected():
            # Log attempt but return empty
            self.logger.log_sql_query(
                query=final_query[:100],
                execution_time=0.0,
                row_count=0,
                error="Database not connected"
            )
            return []

        try:
            cursor = self._connection.cursor()
            cursor.execute(final_query)

            # Get column names
            columns = [column[0] for column in cursor.description] if cursor.description else []

            # Fetch all rows and convert to dictionaries
            rows = cursor.fetchall()
            results = [dict(zip(columns, row)) for row in rows]

            cursor.close()

            # Log success
            execution_time = (datetime.now() - start_time).total_seconds()
            self.logger.log_sql_query(
                query=final_query[:100],
                execution_time=execution_time,
                row_count=len(results)
            )

            return results

        except Exception as e:
            execution_time = (datetime.now() - start_time).total_seconds()
            self.logger.log_sql_query(
                query=final_query[:100],
                execution_time=execution_time,
                row_count=0,
                error=str(e)
            )
            raise SQLExecutionError(f"Query failed: {str(e)}")

    def get_fg_inventory(self, part_number: str, site: str = None) -> List[InventoryResult]:
        """
        Get Finished Goods inventory for a part number.

        Args:
            part_number: The part number to look up
            site: Optional site filter

        Returns:
            List of InventoryResult with available FG inventory
        """
        try:
            query = self._validate_query('fg_inventory')
        except SQLNotConfiguredError:
            # Return empty if not configured
            return []

        # Return mock data if not connected
        if not self.is_connected():
            return self._mock_fg_inventory(part_number, site)

        results = self._execute_query(query, {'part_number': part_number, 'site': site})
        return [
            InventoryResult(
                item_code=r.get('item_code', ''),
                job_number=r.get('job_number'),
                quantity=r.get('quantity', 0),
                location=r.get('location')
            )
            for r in results
        ]

    def get_wip_inventory(self, part_number: str, site: str = None) -> List[InventoryResult]:
        """
        Get Work In Progress inventory for a part number.

        Args:
            part_number: The part number to look up
            site: Optional site filter

        Returns:
            List of InventoryResult with available WIP inventory
        """
        try:
            query = self._validate_query('wip_inventory')
        except SQLNotConfiguredError:
            return []

        if not self.is_connected():
            return self._mock_wip_inventory(part_number, site)

        results = self._execute_query(query, {'part_number': part_number, 'site': site})
        return [
            InventoryResult(
                item_code=r.get('item_code', ''),
                job_number=r.get('job_number'),
                quantity=r.get('quantity', 0),
                location=r.get('location')
            )
            for r in results
        ]

    def get_sw_fg_inventory(self, part_number: str, site: str = None) -> List[InventoryResult]:
        """
        Get Sherwin Williams Finished Goods inventory for a part number.

        Args:
            part_number: The part number to look up
            site: Optional site filter

        Returns:
            List of InventoryResult with available SW FG inventory
        """
        try:
            query = self._validate_query('sw_fg')
        except SQLNotConfiguredError:
            return []

        if not self.is_connected():
            return self._mock_sw_fg_inventory(part_number, site)

        results = self._execute_query(query, {'part_number': part_number, 'site': site})
        return [
            InventoryResult(
                item_code=r.get('item_code', ''),
                job_number=r.get('job_number'),
                quantity=r.get('quantity', 0),
                location=r.get('location')
            )
            for r in results
        ]

    def get_open_jobs(self, part_number: str, site: str = None) -> List[JobResult]:
        """
        Get open production jobs for a part number.

        Args:
            part_number: The part number to look up
            site: Optional site filter

        Returns:
            List of JobResult with open jobs
        """
        try:
            query = self._validate_query('open_jobs')
        except SQLNotConfiguredError:
            return []

        if not self.is_connected():
            return self._mock_open_jobs(part_number, site)

        results = self._execute_query(query, {'part_number': part_number, 'site': site})
        return [
            JobResult(
                job_number=r.get('job_number', ''),
                item_code=r.get('item_code', ''),
                part_number=r.get('part_number', ''),
                quantity_ordered=r.get('quantity_ordered', 0),
                quantity_produced=r.get('quantity_produced', 0),
                quantity_remaining=r.get('quantity_remaining', 0),
                status=r.get('status', 'UNKNOWN')
            )
            for r in results
        ]

    def get_item_mapping(self, part_number: str) -> Optional[ItemMapping]:
        """
        Get item code mapping for a part number.

        Args:
            part_number: The part number to look up

        Returns:
            ItemMapping if found, None otherwise
        """
        try:
            query = self._validate_query('item_mapping')
        except SQLNotConfiguredError:
            return None

        if not self.is_connected():
            return self._mock_item_mapping(part_number)

        results = self._execute_query(query, {'part_number': part_number})
        if results:
            r = results[0]
            return ItemMapping(
                part_number=r.get('part_number', part_number),
                item_code=r.get('item_code', ''),
                description=r.get('description')
            )
        return None

    def get_movements_for_job(self, job_number: str) -> List[MovementResult]:
        """
        Get active movements/allocations for a job.

        Args:
            job_number: The job number to look up

        Returns:
            List of MovementResult with active movements
        """
        try:
            query = self._validate_query('movements')
        except SQLNotConfiguredError:
            return []

        if not self.is_connected():
            return self._mock_movements(job_number)

        results = self._execute_query(query, {'job_number': job_number})
        return [
            MovementResult(
                movement_id=r.get('movement_id', ''),
                job_number=r.get('job_number', job_number),
                quantity=r.get('quantity', 0),
                status=r.get('status', 'UNKNOWN'),
                created_date=r.get('created_date', datetime.now())
            )
            for r in results
        ]

    def get_total_movements_for_job(self, job_number: str) -> int:
        """Get total quantity of active movements for a job"""
        movements = self.get_movements_for_job(job_number)
        return sum(m.quantity for m in movements if m.status in ('ACTIVE', 'PENDING', 'OPEN'))

    # ============== MOCK DATA FOR TESTING ==============

    def _mock_fg_inventory(self, part_number: str, site: str) -> List[InventoryResult]:
        """Return mock FG inventory data"""
        # Return empty to simulate no inventory (forces job creation logic)
        return []

    def _mock_wip_inventory(self, part_number: str, site: str) -> List[InventoryResult]:
        """Return mock WIP inventory data"""
        return []

    def _mock_sw_fg_inventory(self, part_number: str, site: str) -> List[InventoryResult]:
        """Return mock Sherwin Williams FG inventory data"""
        return []

    def _mock_open_jobs(self, part_number: str, site: str) -> List[JobResult]:
        """Return mock open jobs data"""
        return []

    def _mock_item_mapping(self, part_number: str) -> Optional[ItemMapping]:
        """Return mock item mapping"""
        # Generate a mock item code from part number
        if part_number.startswith('L-'):
            # Extract digits from part number
            digits = ''.join(c for c in part_number if c.isdigit())
            if digits:
                return ItemMapping(
                    part_number=part_number,
                    item_code=digits[:7],
                    description=f"Label for {part_number}"
                )
        return None

    def _mock_movements(self, job_number: str) -> List[MovementResult]:
        """Return mock movements data"""
        return []

    # ============== INVENTORY CHECK LOGIC ==============

    def check_inventory_coverage(
        self,
        part_number: str,
        site: str,
        order_qty: int,
        forecast_qty: int
    ) -> Dict:
        """
        Check if inventory and jobs can cover an order.

        Logic (in order):
        1. Check FG inventory - if >= order, create movement from FG
        2. Check WIP inventory - if >= order, create movement against WIP
        3. Check SW FG inventory - if >= order, create movement from SW FG
        4. Check open jobs - if job has capacity (minus existing movements), create movement against job
        5. If nothing covers, recommend new job (stock or rush based on forecast)

        Args:
            part_number: Part number to check
            site: Site code
            order_qty: Order quantity (exact, not rounded)
            forecast_qty: Monthly forecast quantity

        Returns:
            Dict with recommendation:
            {
                'action': 'movement' | 'rush_job' | 'stock_job',
                'source': 'fg' | 'wip' | 'sw_fg' | 'job' | 'new',
                'job_number': str or None,
                'item_code': str or None,
                'quantity': int,
                'fg_available': int,
                'wip_available': int,
                'sw_fg_available': int,
                'jobs_available': int,
                'existing_movements': int,
                'details': str
            }
        """
        result = {
            'action': 'stock_job',
            'source': 'new',
            'job_number': None,
            'item_code': None,
            'quantity': order_qty,
            'fg_available': 0,
            'wip_available': 0,
            'sw_fg_available': 0,
            'jobs_available': 0,
            'existing_movements': 0,
            'details': ''
        }

        # 1. Check FG inventory
        fg_inventory = self.get_fg_inventory(part_number, site)
        total_fg = sum(inv.quantity for inv in fg_inventory)
        result['fg_available'] = total_fg

        if total_fg >= order_qty:
            # Can fulfill from FG
            result['action'] = 'movement'
            result['source'] = 'fg'
            if fg_inventory:
                result['job_number'] = fg_inventory[0].job_number
                result['item_code'] = fg_inventory[0].item_code
            result['details'] = f"FG inventory ({total_fg:,}) covers order ({order_qty:,})"
            return result

        # 2. Check WIP inventory
        wip_inventory = self.get_wip_inventory(part_number, site)
        total_wip = sum(inv.quantity for inv in wip_inventory)
        result['wip_available'] = total_wip

        if total_wip >= order_qty:
            # Can fulfill from WIP
            result['action'] = 'movement'
            result['source'] = 'wip'
            if wip_inventory:
                result['job_number'] = wip_inventory[0].job_number
                result['item_code'] = wip_inventory[0].item_code
            result['details'] = f"WIP inventory ({total_wip:,}) covers order ({order_qty:,})"
            return result

        # 3. Check Sherwin Williams FG inventory
        sw_fg_inventory = self.get_sw_fg_inventory(part_number, site)
        total_sw_fg = sum(inv.quantity for inv in sw_fg_inventory)
        result['sw_fg_available'] = total_sw_fg

        if total_sw_fg >= order_qty:
            # Can fulfill from SW FG
            result['action'] = 'movement'
            result['source'] = 'sw_fg'
            if sw_fg_inventory:
                result['job_number'] = sw_fg_inventory[0].job_number
                result['item_code'] = sw_fg_inventory[0].item_code
            result['details'] = f"SW FG inventory ({total_sw_fg:,}) covers order ({order_qty:,})"
            return result

        # 4. Check open jobs (and their existing movements)
        open_jobs = self.get_open_jobs(part_number, site)
        total_job_capacity = 0

        for job in open_jobs:
            # Get existing movements for this job
            existing_movements = self.get_total_movements_for_job(job.job_number)

            # Calculate available capacity (job remaining - already committed movements)
            available = job.quantity_remaining - existing_movements

            if available > 0:
                total_job_capacity += available
                result['existing_movements'] = existing_movements

                if available >= order_qty:
                    # This job can cover the order
                    result['action'] = 'movement'
                    result['source'] = 'job'
                    result['job_number'] = job.job_number
                    result['item_code'] = job.item_code
                    result['jobs_available'] = available
                    result['details'] = f"Job {job.job_number} has capacity ({available:,}) for order ({order_qty:,}). Existing movements: {existing_movements:,}"
                    return result

        # Record total job capacity even if not enough
        result['jobs_available'] = total_job_capacity

        # 5. Nothing covers - need new job
        # Use forecast quantity for stock job
        job_qty = max(order_qty, forecast_qty) if forecast_qty > 0 else order_qty

        result['action'] = 'stock_job'
        result['source'] = 'new'
        result['quantity'] = job_qty
        result['details'] = f"No coverage found. FG={total_fg:,}, WIP={total_wip:,}, SW_FG={total_sw_fg:,}, Jobs={total_job_capacity:,}. Recommend new job for {job_qty:,}"

        # If order_qty > forecast, this is a rush situation
        if order_qty > forecast_qty and forecast_qty > 0:
            result['action'] = 'rush_job'
            result['details'] = f"Order ({order_qty:,}) exceeds forecast ({forecast_qty:,}). Rush job recommended."

        return result


# Global service instance
_sql_service: Optional[SQLService] = None


def get_sql_service() -> SQLService:
    """Get the global SQL service instance"""
    global _sql_service
    if _sql_service is None:
        _sql_service = SQLService()
    return _sql_service
