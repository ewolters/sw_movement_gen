# MCC Packaging Automation Middleware

Flask-based middleware application for Sherwin-Williams packaging automation. Compares purchase orders against forecasts and inventory, then generates XML files for Fort Dearborn's order entry system.

## Features

- **Excel Forecast Parser** - Parses 52-week forecast files (.xlsx)
- **PO Text Parser** - Parses purchase order files (.txt) from ERP
- **Order vs Forecast vs Inventory Comparison** - Tracks cumulative monthly orders against forecast
- **XML Generation** - Creates Fort Dearborn compatible XML files:
  - Stock Jobs (`sw-stock-MMDDYY#.xml`) - New production orders
  - Stock Movements (`GT-Movement-*.xml`) - Pull from existing inventory
- **Hot Folder Monitoring** - Scheduled daily processing at configurable time
- **SQL Query Configuration** - Configurable queries for ERP/inventory integration
- **Web Dashboard** - Bootstrap-based UI for monitoring and control
- **Audit Logging** - File-based logging for compliance

## Quick Start

### Windows

Double-click `start.bat` or run from command prompt:

```batch
start.bat
```

The script will automatically:
1. Create a Python virtual environment (if not exists)
2. Install dependencies from `requirements.txt`
3. Start the Flask server at http://localhost:5000

### Manual Setup

```bash
# Create virtual environment
python -m venv venv

# Activate (Windows)
venv\Scripts\activate

# Activate (Linux/Mac)
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Run the application
python run.py
```

## Configuration

After starting the app, navigate to http://localhost:5000 and configure:

1. **Forecast Folder** - Path to folder containing .xlsx forecast files
2. **PO Folder** - Path to hot folder for .txt PO files
3. **XML Output Folder** - Path where generated XML files will be saved
4. **Daily Run Time** - Scheduled time for automatic processing (default: 7:00 AM)

Configuration is saved to `config/settings.json`.

## Usage

### Dashboard

The main dashboard shows:
- Today's summary (stock jobs, rush jobs, movements, alerts)
- File upload/selection
- Hot folder configuration
- Quick actions

### Comparison View

Navigate to `/comparison` to see:
- Order vs Forecast vs Inventory comparison table
- Filter by part number or action type
- Generate XML button to create output files
- Export to CSV

### XML Generation

1. Load a Forecast file (.xlsx)
2. Load a PO file (.txt)
3. Go to Comparison view
4. Click "Generate XML"
5. Files are saved to configured output folder

## XML Output Schema

Generated XML files conform to Fort Dearborn's DTD:
```
http://www.fortdearborn.com/dtd/order-entry_1_1.dtd
```

### Stock Jobs (`sw-stock-MMDDYY#.xml`)
- Used for new production orders from forecast
- Quantities rounded UP to nearest 500 (pack size)
- Uses `<book-stock-job>` option
- Freight: `<prepaid />`

### Stock Movements (`GT-Movement-MMDDYY-HHMMSS-###.xml`)
- Used to pull from existing FG/WIP inventory
- Quantities are EXACT (no rounding)
- Uses `<fail-if-insufficient-stock>` or `<fail-if-insufficient-wip>`
- Freight: `<collect />`

## Business Rules

| Output Type | Quantity Rounding |
|-------------|-------------------|
| Stock Job | Round UP to 500 |
| Rush Job | Round UP to 500 |
| Stock Movement | Exact (no rounding) |

## Project Structure

```
PAINT ON DEMAND/
├── app/
│   ├── main.py              # Flask routes and API endpoints
│   ├── parsers/
│   │   ├── excel_parser.py  # Forecast file parser
│   │   └── txt_parser.py    # PO file parser
│   ├── services/
│   │   ├── config.py        # Configuration management
│   │   ├── logger.py        # Audit logging
│   │   ├── order_tracker.py # Cumulative order tracking
│   │   ├── sql_service.py   # SQL/inventory integration
│   │   └── xml_generator.py # XML output generation
│   └── templates/           # HTML templates
├── inputs/                  # Input files (forecast, PO)
├── outputs/
│   ├── xml/                 # Generated XML files
│   ├── logs/                # Audit logs
│   └── archive/             # Processed files
├── config/                  # Configuration files
├── start.bat                # Windows startup script
├── run.py                   # Application entry point
├── requirements.txt         # Python dependencies
└── TECH_SPEC.md            # Technical specification
```

## Requirements

- Python 3.10+
- Dependencies in `requirements.txt`:
  - Flask
  - openpyxl
  - python-dateutil

## SQL Integration

The SQL Query page (`/sql`) allows configuration of queries for:
- FG Inventory lookup
- WIP Inventory lookup
- Open Jobs lookup
- Part number to Item code mapping
- Active movements lookup

Queries use placeholders: `{part_number}`, `{site}`, `{item_code}`

## License

Proprietary - Sherwin-Williams / MCC Packaging
