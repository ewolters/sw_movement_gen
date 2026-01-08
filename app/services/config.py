"""
Configuration Service for Hot Folder Paths and SQL Queries

Stores user configuration in a JSON file for persistence.
"""

import json
from pathlib import Path
from dataclasses import dataclass, asdict, field
from typing import Optional, Dict

# Config file location
CONFIG_DIR = Path(__file__).parent.parent.parent / "config"
CONFIG_FILE = CONFIG_DIR / "settings.json"

# SQL Query Types
SQL_QUERY_TYPES = [
    'fg_inventory',      # Finished Goods inventory lookup
    'wip_inventory',     # Work In Progress inventory lookup
    'open_jobs',         # Open production jobs lookup
    'item_mapping',      # Part number to Item code mapping
    'movements',         # Active movements/allocations lookup
    'sw_fg',             # Sherwin Williams FG inventory lookup
]


@dataclass
class SQLQueries:
    """SQL query templates for ERP integration"""
    fg_inventory: Optional[str] = None       # Query to get FG inventory by part/site
    wip_inventory: Optional[str] = None      # Query to get WIP inventory by part/site
    open_jobs: Optional[str] = None          # Query to get open jobs by part/site
    item_mapping: Optional[str] = None       # Query to map part number to item code
    movements: Optional[str] = None          # Query to get active movements for a job
    sw_fg: Optional[str] = None              # Query to get Sherwin Williams FG inventory

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> 'SQLQueries':
        return cls(
            fg_inventory=data.get('fg_inventory'),
            wip_inventory=data.get('wip_inventory'),
            open_jobs=data.get('open_jobs'),
            item_mapping=data.get('item_mapping'),
            movements=data.get('movements'),
            sw_fg=data.get('sw_fg')
        )

    def get_query(self, query_type: str) -> Optional[str]:
        """Get query by type name"""
        return getattr(self, query_type, None)

    def set_query(self, query_type: str, query: str) -> bool:
        """Set query by type name"""
        if query_type in SQL_QUERY_TYPES:
            setattr(self, query_type, query if query.strip() else None)
            return True
        return False


@dataclass
class AppConfig:
    """Application configuration"""
    forecast_folder: Optional[str] = None  # Path to folder containing forecast .xlsx files
    po_folder: Optional[str] = None  # Path to hot folder containing PO .txt files
    xml_output_folder: Optional[str] = None  # Path to save generated XML files
    scheduler_hour: int = 7  # Hour to run daily processing (24h format)
    scheduler_minute: int = 0  # Minute to run daily processing
    last_forecast_file: Optional[str] = None  # Last loaded forecast filename
    last_forecast_modified: Optional[str] = None  # Last modified timestamp of forecast file
    sql_queries: SQLQueries = field(default_factory=SQLQueries)  # SQL query templates
    db_credentials: Optional[Dict] = None  # Database connection credentials

    def to_dict(self) -> dict:
        d = asdict(self)
        # Handle nested SQLQueries
        d['sql_queries'] = self.sql_queries.to_dict()
        return d

    @classmethod
    def from_dict(cls, data: dict) -> 'AppConfig':
        sql_data = data.get('sql_queries', {})
        return cls(
            forecast_folder=data.get('forecast_folder'),
            po_folder=data.get('po_folder'),
            xml_output_folder=data.get('xml_output_folder'),
            scheduler_hour=data.get('scheduler_hour', 7),
            scheduler_minute=data.get('scheduler_minute', 0),
            last_forecast_file=data.get('last_forecast_file'),
            last_forecast_modified=data.get('last_forecast_modified'),
            sql_queries=SQLQueries.from_dict(sql_data) if sql_data else SQLQueries(),
            db_credentials=data.get('db_credentials')
        )


class ConfigService:
    """Manages application configuration"""

    _instance = None
    _config: AppConfig = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._load_config()
        return cls._instance

    def _load_config(self):
        """Load configuration from file"""
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)

        if CONFIG_FILE.exists():
            try:
                with open(CONFIG_FILE, 'r') as f:
                    data = json.load(f)
                self._config = AppConfig.from_dict(data)
            except (json.JSONDecodeError, Exception):
                self._config = AppConfig()
        else:
            self._config = AppConfig()
            self._save_config()

    def _save_config(self):
        """Save configuration to file"""
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        with open(CONFIG_FILE, 'w') as f:
            json.dump(self._config.to_dict(), f, indent=2)

    @property
    def config(self) -> AppConfig:
        return self._config

    def set_forecast_folder(self, path: Optional[str]) -> bool:
        """Set forecast folder path. Returns True if valid."""
        if path:
            p = Path(path)
            if not p.exists():
                return False
            if not p.is_dir():
                return False
        self._config.forecast_folder = path
        self._save_config()
        return True

    def set_po_folder(self, path: Optional[str]) -> bool:
        """Set PO hot folder path. Returns True if valid."""
        if path:
            p = Path(path)
            if not p.exists():
                return False
            if not p.is_dir():
                return False
        self._config.po_folder = path
        self._save_config()
        return True

    def set_xml_output_folder(self, path: Optional[str]) -> bool:
        """Set XML output folder path. Creates if doesn't exist."""
        if path:
            p = Path(path)
            try:
                p.mkdir(parents=True, exist_ok=True)
            except Exception:
                return False
        self._config.xml_output_folder = path
        self._save_config()
        return True

    def set_scheduler_time(self, hour: int, minute: int = 0) -> bool:
        """Set scheduler run time"""
        if not (0 <= hour <= 23) or not (0 <= minute <= 59):
            return False
        self._config.scheduler_hour = hour
        self._config.scheduler_minute = minute
        self._save_config()
        return True

    def get_forecast_files(self) -> list:
        """Get list of .xlsx files in forecast folder"""
        if not self._config.forecast_folder:
            return []
        folder = Path(self._config.forecast_folder)
        if not folder.exists():
            return []
        return sorted([f.name for f in folder.glob("*.xlsx")])

    def get_po_files(self) -> list:
        """Get list of .txt files in PO folder"""
        if not self._config.po_folder:
            return []
        folder = Path(self._config.po_folder)
        if not folder.exists():
            return []
        return sorted([f.name for f in folder.glob("*.txt")])

    def is_forecast_folder_configured(self) -> bool:
        """Check if forecast folder is configured and valid"""
        if not self._config.forecast_folder:
            return False
        return Path(self._config.forecast_folder).exists()

    def is_po_folder_configured(self) -> bool:
        """Check if PO folder is configured and valid"""
        if not self._config.po_folder:
            return False
        return Path(self._config.po_folder).exists()

    def get_latest_forecast_file(self) -> Optional[Path]:
        """Get the most recently modified forecast file in the folder"""
        if not self.is_forecast_folder_configured():
            return None
        folder = Path(self._config.forecast_folder)
        xlsx_files = list(folder.glob("*.xlsx"))
        if not xlsx_files:
            return None
        # Return most recently modified
        return max(xlsx_files, key=lambda f: f.stat().st_mtime)

    def has_forecast_changed(self) -> tuple:
        """
        Check if forecast file has changed since last load.

        Returns:
            (has_changed: bool, new_file: Path or None, reason: str)
        """
        latest = self.get_latest_forecast_file()
        if not latest:
            return False, None, "No forecast files found"

        latest_mtime = latest.stat().st_mtime
        latest_mtime_str = str(latest_mtime)

        # Check if it's a different file or same file with new timestamp
        if self._config.last_forecast_file != latest.name:
            return True, latest, f"New file: {latest.name}"

        if self._config.last_forecast_modified != latest_mtime_str:
            return True, latest, f"File modified: {latest.name}"

        return False, latest, "No changes"

    def update_forecast_tracking(self, filename: str, modified_time: float):
        """Update tracking info after loading a forecast"""
        self._config.last_forecast_file = filename
        self._config.last_forecast_modified = str(modified_time)
        self._save_config()

    # SQL Query Management
    def get_sql_query(self, query_type: str) -> Optional[str]:
        """Get a SQL query by type"""
        return self._config.sql_queries.get_query(query_type)

    def set_sql_query(self, query_type: str, query: str) -> bool:
        """Set a SQL query by type"""
        if self._config.sql_queries.set_query(query_type, query):
            self._save_config()
            return True
        return False

    def get_all_sql_queries(self) -> dict:
        """Get all SQL queries as a dictionary"""
        return self._config.sql_queries.to_dict()

    def set_all_sql_queries(self, queries: dict) -> bool:
        """Set multiple SQL queries at once"""
        for query_type, query in queries.items():
            self._config.sql_queries.set_query(query_type, query or '')
        self._save_config()
        return True

    def is_sql_configured(self, query_type: str) -> bool:
        """Check if a specific SQL query is configured"""
        query = self.get_sql_query(query_type)
        return query is not None and query.strip() != ''

    def get_configured_sql_count(self) -> int:
        """Get count of configured SQL queries"""
        return sum(1 for qt in SQL_QUERY_TYPES if self.is_sql_configured(qt))

    # Database Credentials Management
    def get_db_credentials(self) -> Optional[Dict]:
        """Get database credentials"""
        return self._config.db_credentials

    def set_db_credentials(self, credentials: Dict) -> bool:
        """
        Set database credentials.

        Args:
            credentials: Dict with connection info:
                - connection_string: Full ODBC connection string, OR
                - driver: ODBC driver name
                - server: Database server address
                - database: Database name
                - username: Database username (optional for Windows auth)
                - password: Database password (optional for Windows auth)
                - trusted_connection: Use Windows authentication (bool)

        Returns:
            True if credentials were saved
        """
        # Build connection string if individual fields provided
        if credentials.get('driver') and not credentials.get('connection_string'):
            parts = [f"DRIVER={{{credentials['driver']}}}"]

            if credentials.get('server'):
                parts.append(f"SERVER={credentials['server']}")
            if credentials.get('database'):
                parts.append(f"DATABASE={credentials['database']}")

            if credentials.get('trusted_connection'):
                parts.append("Trusted_Connection=yes")
            else:
                if credentials.get('username'):
                    parts.append(f"UID={credentials['username']}")
                if credentials.get('password'):
                    parts.append(f"PWD={credentials['password']}")

            credentials['connection_string'] = ';'.join(parts)

        self._config.db_credentials = credentials
        self._save_config()
        return True

    def clear_db_credentials(self):
        """Clear database credentials"""
        self._config.db_credentials = None
        self._save_config()

    def is_db_configured(self) -> bool:
        """Check if database credentials are configured"""
        creds = self._config.db_credentials
        return creds is not None and bool(creds.get('connection_string'))


def get_config() -> ConfigService:
    """Get the singleton config service instance"""
    return ConfigService()
