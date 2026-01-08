"""
MCC Packaging Automation Middleware
Flask Application Entry Point
"""

from flask import Flask, render_template, request, jsonify, send_file
from pathlib import Path
import os
import json
import shutil
from datetime import datetime, timedelta

# Import parsers
from app.parsers.txt_parser import parse_po_file, get_all_details, get_unique_parts
from app.parsers.excel_parser import parse_forecast_file

# Import services
from app.services.logger import get_logger, LogEventType
from app.services.config import get_config
from app.services.order_tracker import get_order_tracker
from app.services.sql_service import get_sql_service
from app.services.xml_generator import (
    get_xml_generator, StockJob, StockJobLine, StockMovement, MovementLine
)

app = Flask(__name__,
            template_folder='templates',
            static_folder='static')

# Configuration
BASE_DIR = Path(__file__).parent.parent
INPUTS_DIR = BASE_DIR / "inputs"
OUTPUTS_DIR = BASE_DIR / "outputs"
XML_DIR = OUTPUTS_DIR / "xml"
LOGS_DIR = OUTPUTS_DIR / "logs"
ARCHIVE_DIR = OUTPUTS_DIR / "archive"

# Ensure directories exist
XML_DIR.mkdir(parents=True, exist_ok=True)
LOGS_DIR.mkdir(parents=True, exist_ok=True)
ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)

# In-memory state
app_state = {
    "forecast_data": None,
    "forecast_file": None,
    "po_data": None,
    "po_file": None,
    "alerts": [],
    "last_run_time": None,
    "retry_scheduled": False
}


# ============== ROUTES ==============

@app.route('/')
def index():
    """Main dashboard"""
    logger = get_logger()
    config_service = get_config()
    config = config_service.config

    summary = logger.get_today_summary()

    # Get files from configured folders
    forecast_files = config_service.get_forecast_files() if config_service.is_forecast_folder_configured() else []
    po_files = config_service.get_po_files() if config_service.is_po_folder_configured() else []

    # Calculate next run time
    next_run_time = None
    if config_service.is_po_folder_configured():
        now = datetime.now()
        target = now.replace(hour=config.scheduler_hour, minute=config.scheduler_minute, second=0, microsecond=0)
        if now >= target:
            target += timedelta(days=1)
        next_run_time = target.strftime("%Y-%m-%d %H:%M")

    return render_template('index.html',
                         summary=summary,
                         config=config,
                         forecast_loaded=app_state["forecast_file"],
                         po_loaded=app_state["po_file"],
                         forecast_folder_configured=config_service.is_forecast_folder_configured(),
                         po_folder_configured=config_service.is_po_folder_configured(),
                         forecast_files=forecast_files,
                         po_files=po_files,
                         next_run_time=next_run_time,
                         last_run_time=app_state.get("last_run_time"))


@app.route('/comparison')
def comparison():
    """Order vs Forecast vs Inventory comparison view"""
    return render_template('comparison.html')


@app.route('/jobs')
def jobs():
    """Jobs overview (stock jobs, rush jobs, movements)"""
    return render_template('jobs.html')


@app.route('/sql')
def sql_executor():
    """SQL Query Configuration"""
    config_service = get_config()
    sql_service = get_sql_service()
    db_creds = config_service.get_db_credentials() or {}

    return render_template('sql.html',
                         sql_queries=config_service.config.sql_queries,
                         configured_count=config_service.get_configured_sql_count(),
                         connected=sql_service.is_connected(),
                         db_configured=config_service.is_db_configured(),
                         db_credentials=db_creds,
                         connection_status=sql_service.get_connection_status())


@app.route('/logs')
def logs_dashboard():
    """Logs dashboard"""
    logger = get_logger()
    available_dates = logger.get_available_dates()
    return render_template('logs.html', available_dates=available_dates)


# ============== CONFIG API ==============

@app.route('/api/config', methods=['GET'])
def get_config_api():
    """Get current configuration"""
    config_service = get_config()
    return jsonify({
        "forecast_folder": config_service.config.forecast_folder,
        "po_folder": config_service.config.po_folder,
        "scheduler_hour": config_service.config.scheduler_hour,
        "scheduler_minute": config_service.config.scheduler_minute
    })


@app.route('/api/config', methods=['POST'])
def save_config_api():
    """Save configuration"""
    data = request.get_json()
    config_service = get_config()
    logger = get_logger()

    errors = []

    # Validate and set forecast folder
    forecast_folder = data.get('forecast_folder')
    if forecast_folder:
        if not config_service.set_forecast_folder(forecast_folder):
            errors.append(f"Forecast folder path invalid: {forecast_folder}")
    else:
        config_service.set_forecast_folder(None)

    # Validate and set PO folder
    po_folder = data.get('po_folder')
    if po_folder:
        if not config_service.set_po_folder(po_folder):
            errors.append(f"PO folder path invalid: {po_folder}")
    else:
        config_service.set_po_folder(None)

    # Validate and set XML output folder
    xml_output_folder = data.get('xml_output_folder')
    if xml_output_folder:
        if not config_service.set_xml_output_folder(xml_output_folder):
            errors.append(f"XML output folder path invalid: {xml_output_folder}")
    else:
        config_service.set_xml_output_folder(None)

    # Set scheduler time
    hour = data.get('scheduler_hour', 7)
    minute = data.get('scheduler_minute', 0)
    if not config_service.set_scheduler_time(hour, minute):
        errors.append("Invalid scheduler time")

    if errors:
        return jsonify({"success": False, "errors": errors}), 400

    logger.log_user_action("Configuration updated", json.dumps(data))

    return jsonify({
        "success": True,
        "message": "Configuration saved"
    })


# ============== FILE LOADING FROM CONFIGURED FOLDERS ==============

@app.route('/api/load/forecast', methods=['POST'])
def load_forecast_from_folder():
    """Load forecast file from configured folder"""
    config_service = get_config()

    if not config_service.is_forecast_folder_configured():
        return jsonify({"error": "Forecast folder not configured"}), 400

    data = request.get_json()
    filename = data.get('filename')

    if not filename:
        return jsonify({"error": "No filename provided"}), 400

    filepath = Path(config_service.config.forecast_folder) / filename

    if not filepath.exists():
        return jsonify({"error": f"File not found: {filename}"}), 404

    # Parse file
    forecast_data, errors = parse_forecast_file(str(filepath))

    if forecast_data:
        app_state["forecast_data"] = forecast_data
        app_state["forecast_file"] = filename

        logger = get_logger()
        logger.log_file_processed(filename, len(forecast_data.records), len(errors))
        logger.log_user_action("Loaded forecast from folder", filename)

        return jsonify({
            "success": True,
            "filename": filename,
            "records": len(forecast_data.records),
            "unique_parts": len(forecast_data.get_unique_parts()),
            "errors": errors
        })
    else:
        return jsonify({"error": "Failed to parse file", "details": errors}), 400


@app.route('/api/load/po', methods=['POST'])
def load_po_from_folder():
    """Load PO file from configured folder"""
    config_service = get_config()

    if not config_service.is_po_folder_configured():
        return jsonify({"error": "PO folder not configured"}), 400

    data = request.get_json()
    filename = data.get('filename')

    if not filename:
        return jsonify({"error": "No filename provided"}), 400

    filepath = Path(config_service.config.po_folder) / filename

    if not filepath.exists():
        return jsonify({"error": f"File not found: {filename}"}), 404

    # Parse file
    pos, errors = parse_po_file(str(filepath))

    if pos:
        all_details = get_all_details(pos)
        app_state["po_data"] = pos
        app_state["po_file"] = filename

        logger = get_logger()
        logger.log_file_processed(filename, len(all_details), len(errors))
        logger.log_user_action("Loaded PO from folder", filename)

        return jsonify({
            "success": True,
            "filename": filename,
            "purchase_orders": len(pos),
            "line_items": len(all_details),
            "unique_parts": len(get_unique_parts(pos)),
            "errors": errors
        })
    else:
        return jsonify({"error": "Failed to parse file", "details": errors}), 400


# ============== FILE UPLOAD API ==============

@app.route('/api/upload/forecast', methods=['POST'])
def upload_forecast():
    """Upload and parse forecast Excel file"""
    if 'file' not in request.files:
        return jsonify({"error": "No file provided"}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "No file selected"}), 400

    # Save file
    filename = file.filename
    filepath = INPUTS_DIR / filename
    file.save(filepath)

    # Parse file
    forecast_data, errors = parse_forecast_file(str(filepath))

    if forecast_data:
        app_state["forecast_data"] = forecast_data
        app_state["forecast_file"] = filename

        logger = get_logger()
        logger.log_file_processed(filename, len(forecast_data.records), len(errors))
        logger.log_user_action("Uploaded forecast file", filename)

        return jsonify({
            "success": True,
            "filename": filename,
            "records": len(forecast_data.records),
            "unique_parts": len(forecast_data.get_unique_parts()),
            "sites": forecast_data.get_unique_sites(),
            "months": forecast_data.months_available,
            "errors": errors
        })
    else:
        return jsonify({"error": "Failed to parse file", "details": errors}), 400


@app.route('/api/upload/po', methods=['POST'])
def upload_po():
    """Upload and parse PO text file"""
    if 'file' not in request.files:
        return jsonify({"error": "No file provided"}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "No file selected"}), 400

    # Save file
    filename = file.filename
    filepath = INPUTS_DIR / filename
    file.save(filepath)

    # Parse file
    pos, errors = parse_po_file(str(filepath))

    if pos:
        all_details = get_all_details(pos)
        app_state["po_data"] = pos
        app_state["po_file"] = filename

        logger = get_logger()
        logger.log_file_processed(filename, len(all_details), len(errors))
        logger.log_user_action("Uploaded PO file", filename)

        return jsonify({
            "success": True,
            "filename": filename,
            "purchase_orders": len(pos),
            "line_items": len(all_details),
            "unique_parts": len(get_unique_parts(pos)),
            "errors": errors
        })
    else:
        return jsonify({"error": "Failed to parse file", "details": errors}), 400


# ============== DATA API ==============

@app.route('/api/forecast/data')
def get_forecast_data():
    """Get loaded forecast data"""
    if not app_state["forecast_data"]:
        return jsonify({"error": "No forecast loaded"}), 404

    forecast = app_state["forecast_data"]

    # Return paginated data
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 100, type=int)
    search = request.args.get('search', '')

    records = forecast.records
    if search:
        records = [r for r in records if search.upper() in r.part_number.upper()]

    start = (page - 1) * per_page
    end = start + per_page
    page_records = records[start:end]

    return jsonify({
        "total": len(records),
        "page": page,
        "per_page": per_page,
        "data": [
            {
                "part_number": r.part_number,
                "description": r.description,
                "site": r.site,
                "yearly_sum": r.yearly_sum,
                "monthly": r.monthly_forecasts
            }
            for r in page_records
        ]
    })


@app.route('/api/po/data')
def get_po_data():
    """Get loaded PO data"""
    if not app_state["po_data"]:
        return jsonify({"error": "No PO loaded"}), 404

    pos = app_state["po_data"]
    all_details = get_all_details(pos)

    # Return paginated data
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 100, type=int)
    search = request.args.get('search', '')

    if search:
        all_details = [d for d in all_details if search.upper() in d.part_number.upper()]

    start = (page - 1) * per_page
    end = start + per_page
    page_details = all_details[start:end]

    return jsonify({
        "total": len(all_details),
        "page": page,
        "per_page": per_page,
        "data": [
            {
                "po_number": d.po_number,
                "site_code": d.site_code,
                "line_number": d.line_number,
                "part_number": d.part_number,
                "quantity": d.quantity,
                "quantity_rounded": d.quantity_rounded,
                "unit_price": d.unit_price,
                "due_date": d.due_date.strftime("%m/%d/%Y")
            }
            for d in page_details
        ]
    })


@app.route('/api/comparison/data')
def get_comparison_data():
    """
    Get comparison data (order vs forecast vs inventory).

    Compares CUMULATIVE monthly orders against monthly forecast.
    Uses SQL service to check FG/WIP inventory and open jobs.
    Recommends action: Movement (from FG/WIP/Job), Stock Job, or Rush Job.
    """
    if not app_state["po_data"]:
        return jsonify({"error": "No PO loaded"}), 404

    pos = app_state["po_data"]
    forecast = app_state["forecast_data"]
    all_details = get_all_details(pos)
    order_tracker = get_order_tracker()
    sql_service = get_sql_service()

    now = datetime.now()
    current_year = now.year
    current_month = now.month

    comparison_data = []
    alerts = []

    # Track cumulative by part+site for this comparison session
    cumulative_cache = {}

    for detail in all_details:
        # Get forecast for current month
        forecast_qty = 0
        forecast_record = None

        if forecast:
            forecast_record = forecast.get_by_part_and_site(detail.part_number, detail.site_code)
            if not forecast_record:
                matches = forecast.get_by_part(detail.part_number)
                if matches:
                    forecast_record = matches[0]

            if forecast_record:
                forecast_qty = forecast_record.get_current_month_forecast()
                if forecast_qty == 0:
                    forecast_qty = forecast_record.yearly_sum / 12

        # Get CUMULATIVE orders for this part+site this month
        cache_key = f"{detail.part_number}|{detail.site_code}"
        if cache_key not in cumulative_cache:
            prior_qty, prior_rounded = order_tracker.get_cumulative_by_part_site(
                current_year, current_month, detail.part_number, detail.site_code
            )
            cumulative_cache[cache_key] = {
                "prior": prior_rounded,
                "current_po": 0
            }

        cumulative_cache[cache_key]["current_po"] += detail.quantity_rounded
        prior_orders = cumulative_cache[cache_key]["prior"]
        current_po_total = cumulative_cache[cache_key]["current_po"]
        cumulative_total = prior_orders + current_po_total

        # Use SQL service to check inventory coverage
        coverage = sql_service.check_inventory_coverage(
            part_number=detail.part_number,
            site=detail.site_code,
            order_qty=detail.quantity_rounded,
            forecast_qty=round(forecast_qty)
        )

        # Get inventory totals from coverage check
        fg_qty = coverage['fg_available']
        wip_qty = coverage['wip_available']
        jobs_qty = coverage['jobs_available']
        total_inventory = fg_qty + wip_qty

        # Determine action from coverage check
        action = coverage['action']
        action_source = coverage['source']
        job_number = coverage['job_number']

        # Format action display
        if action == 'movement':
            if action_source == 'fg':
                action_display = "Movement (FG)"
            elif action_source == 'wip':
                action_display = "Movement (WIP)"
            else:
                action_display = f"Movement ({job_number})"
        elif action == 'stock_job':
            action_display = "Stock Job"
        elif action == 'rush_job':
            action_display = "Rush Job"
        else:
            action_display = action.title()

        # Calculate gap (positive = covered, negative = short)
        gap = total_inventory - detail.quantity_rounded

        # Generate alerts
        if action in ('stock_job', 'rush_job'):
            alerts.append({
                "type": "needs_job",
                "part": detail.part_number,
                "message": f"{action_display} needed: {coverage['details']}",
                "quantity": coverage['quantity']
            })

        if cumulative_total > forecast_qty and forecast_qty > 0:
            overage = cumulative_total - forecast_qty
            alerts.append({
                "type": "exceeds_forecast",
                "part": detail.part_number,
                "message": f"Cumulative ({cumulative_total:,}) exceeds forecast ({forecast_qty:,.0f}) by {overage:,}",
                "prior_orders": prior_orders,
                "current_order": detail.quantity_rounded
            })

        comparison_data.append({
            "po_number": detail.po_number,
            "part_number": detail.part_number,
            "site": detail.site_code,
            "order_qty": detail.quantity,
            "order_qty_rounded": detail.quantity_rounded,
            "prior_month_orders": prior_orders,
            "cumulative_month": cumulative_total,
            "forecast_qty": round(forecast_qty),
            "forecast_remaining": max(0, round(forecast_qty) - prior_orders),
            "fg_qty": fg_qty,
            "wip_qty": wip_qty,
            "jobs_qty": jobs_qty,
            "inventory_qty": total_inventory,
            "gap": gap,
            "action": action_display,
            "action_type": action,
            "job_number": job_number,
            "due_date": detail.due_date.strftime("%m/%d/%Y")
        })

    app_state["alerts"] = alerts

    return jsonify({
        "data": comparison_data,
        "alerts": alerts[:20],
        "total_alerts": len(alerts),
        "month": f"{current_year}-{current_month:02d}"
    })


@app.route('/api/logs/data')
def get_logs_data():
    """Get log entries"""
    logger = get_logger()
    date_str = request.args.get('date', datetime.now().strftime('%Y-%m-%d'))
    event_type = request.args.get('type', '')
    search = request.args.get('search', '')

    try:
        date = datetime.strptime(date_str, '%Y-%m-%d')
    except ValueError:
        date = datetime.now()

    entries = logger.get_entries_for_date(date)

    # Filter by type
    if event_type:
        entries = [e for e in entries if e.event_type.value == event_type]

    # Filter by search
    if search:
        search_lower = search.lower()
        entries = [e for e in entries if
                   search_lower in e.message.lower() or
                   (e.details and search_lower in e.details.lower()) or
                   (e.part_number and search_lower in e.part_number.lower())]

    return jsonify({
        "date": date_str,
        "total": len(entries),
        "entries": [
            {
                "timestamp": e.timestamp.strftime("%H:%M:%S"),
                "type": e.event_type.value,
                "message": e.message,
                "details": e.details,
                "part_number": e.part_number,
                "quantity": e.quantity,
                "po_number": e.po_number,
                "xml_file": e.xml_file
            }
            for e in reversed(entries)  # Most recent first
        ]
    })


@app.route('/api/logs/summary')
def get_logs_summary():
    """Get today's summary"""
    logger = get_logger()
    summary = logger.get_today_summary()
    return jsonify(summary)


@app.route('/api/alerts')
def get_alerts():
    """Get current alerts"""
    return jsonify({
        "alerts": app_state["alerts"][:20],
        "total": len(app_state["alerts"])
    })


# ============== SQL QUERY API ==============

@app.route('/api/sql/queries', methods=['GET'])
def get_sql_queries():
    """Get all configured SQL queries"""
    config_service = get_config()
    return jsonify(config_service.get_all_sql_queries())


@app.route('/api/sql/queries', methods=['POST'])
def save_sql_queries():
    """Save SQL queries to configuration"""
    data = request.get_json()
    config_service = get_config()
    logger = get_logger()

    try:
        config_service.set_all_sql_queries(data)
        logger.log_user_action("SQL queries updated", f"{config_service.get_configured_sql_count()} queries configured")
        return jsonify({"success": True})
    except Exception as e:
        logger.log_error("SQL Config", str(e))
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/sql/test', methods=['POST'])
def test_sql_query():
    """Test a SQL query (returns mock data if not connected)"""
    data = request.get_json()
    query_type = data.get('query_type')
    query = data.get('query', '').strip()

    if not query:
        return jsonify({"error": "No query provided"}), 400

    sql_service = get_sql_service()
    logger = get_logger()

    # For testing, we'll return mock results
    # In production, this would execute the actual query
    import time
    start = time.time()

    try:
        # Simulate query execution
        mock_data = []

        if query_type == 'fg_inventory':
            mock_data = [
                {"item_code": "2029033", "job_number": "7755514", "quantity": 15000, "location": "A1"},
                {"item_code": "2029033", "job_number": "7762740", "quantity": 4500, "location": "B2"}
            ]
        elif query_type == 'wip_inventory':
            mock_data = [
                {"item_code": "2029033", "job_number": "7771759", "quantity": 8000, "location": "WIP-1"}
            ]
        elif query_type == 'open_jobs':
            mock_data = [
                {"job_number": "7771759", "item_code": "2029033", "part_number": "L-61370444-14",
                 "quantity_ordered": 25000, "quantity_produced": 8000, "quantity_remaining": 17000, "status": "OPEN"}
            ]
        elif query_type == 'item_mapping':
            mock_data = [
                {"part_number": "L-61370444-14", "item_code": "2029033", "description": "Label 14oz Can"}
            ]
        elif query_type == 'movements':
            mock_data = [
                {"movement_id": "MOV-001", "job_number": "7771759", "quantity": 5000, "status": "ACTIVE",
                 "created_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
            ]

        execution_time = round(time.time() - start, 3)

        logger.log_sql_query(query[:100], execution_time, len(mock_data))

        return jsonify({
            "success": True,
            "connected": sql_service.is_connected(),
            "query_type": query_type,
            "row_count": len(mock_data),
            "execution_time": execution_time,
            "data": mock_data
        })

    except Exception as e:
        logger.log_error("SQL Test", str(e))
        return jsonify({"error": str(e)}), 500


@app.route('/api/sql/credentials', methods=['GET'])
def get_db_credentials():
    """Get database credentials (without password)"""
    config_service = get_config()
    creds = config_service.get_db_credentials() or {}

    # Return credentials without password for security
    safe_creds = {
        'driver': creds.get('driver', ''),
        'server': creds.get('server', ''),
        'database': creds.get('database', ''),
        'username': creds.get('username', ''),
        'trusted_connection': creds.get('trusted_connection', False),
        'has_password': bool(creds.get('password')),
        'has_connection_string': bool(creds.get('connection_string'))
    }
    return jsonify(safe_creds)


@app.route('/api/sql/credentials', methods=['POST'])
def save_db_credentials():
    """Save database credentials"""
    data = request.get_json()
    config_service = get_config()
    logger = get_logger()

    try:
        config_service.set_db_credentials(data)
        logger.log_user_action("Database credentials updated", f"Server: {data.get('server', 'N/A')}")
        return jsonify({"success": True})
    except Exception as e:
        logger.log_error("DB Credentials", str(e))
        return jsonify({"success": False, "error": str(e)}), 500


@app.route('/api/sql/credentials', methods=['DELETE'])
def clear_db_credentials():
    """Clear database credentials"""
    config_service = get_config()
    sql_service = get_sql_service()
    logger = get_logger()

    sql_service.disconnect()
    config_service.clear_db_credentials()
    logger.log_user_action("Database credentials cleared", "")
    return jsonify({"success": True})


@app.route('/api/sql/connect', methods=['POST'])
def connect_database():
    """Attempt to connect to database"""
    sql_service = get_sql_service()
    logger = get_logger()

    success, message = sql_service.connect()

    if success:
        return jsonify({"success": True, "message": message})
    else:
        return jsonify({"success": False, "error": message}), 400


@app.route('/api/sql/disconnect', methods=['POST'])
def disconnect_database():
    """Disconnect from database"""
    sql_service = get_sql_service()
    logger = get_logger()

    sql_service.disconnect()
    logger.log_user_action("Database disconnected", "")
    return jsonify({"success": True})


@app.route('/api/sql/status', methods=['GET'])
def get_db_status():
    """Get database connection status"""
    sql_service = get_sql_service()
    return jsonify(sql_service.get_connection_status())


# ============== XML GENERATION API ==============

@app.route('/api/xml/config', methods=['GET'])
def get_xml_config():
    """Get current XML output configuration"""
    config_service = get_config()
    xml_gen = get_xml_generator()

    return jsonify({
        "output_folder": config_service.config.xml_output_folder or str(OUTPUTS_DIR / "xml"),
        "default_delivery_address": "13316",
        "default_movement_address": "16291"
    })


@app.route('/api/xml/config', methods=['POST'])
def save_xml_config():
    """Save XML output configuration"""
    data = request.get_json()
    config_service = get_config()
    logger = get_logger()

    output_folder = data.get('output_folder')
    if output_folder:
        # Validate folder path
        try:
            Path(output_folder).mkdir(parents=True, exist_ok=True)
            config_service.set_xml_output_folder(output_folder)
            logger.log_user_action("XML output folder configured", output_folder)
            return jsonify({"success": True, "output_folder": output_folder})
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 400

    return jsonify({"success": False, "error": "No output folder provided"}), 400


@app.route('/api/xml/generate/stock-jobs', methods=['POST'])
def generate_stock_jobs():
    """
    Generate stock job XML from comparison data.

    Request body:
    {
        "items": [
            {
                "part_number": "L-XXX",
                "quantity": 1000,
                "price": 100.00,
                "delivery_address": "13316",
                "delivery_date": "2026-01-27"
            }
        ],
        "output_folder": "/path/to/output" (optional)
    }
    """
    data = request.get_json()
    logger = get_logger()
    config_service = get_config()
    xml_gen = get_xml_generator()

    items = data.get('items', [])
    if not items:
        return jsonify({"error": "No items provided"}), 400

    # Get output folder
    output_folder = data.get('output_folder') or config_service.config.xml_output_folder
    if not output_folder:
        output_folder = str(OUTPUTS_DIR / "xml")

    try:
        # Group items by delivery address/date into jobs
        jobs_by_delivery = {}
        for item in items:
            delivery_key = f"{item.get('delivery_address', '13316')}|{item.get('delivery_date', '')}"
            if delivery_key not in jobs_by_delivery:
                delivery_date = None
                if item.get('delivery_date'):
                    try:
                        delivery_date = datetime.strptime(item['delivery_date'], '%Y-%m-%d')
                    except ValueError:
                        delivery_date = datetime.now() + timedelta(days=21)

                jobs_by_delivery[delivery_key] = StockJob(
                    lines=[],
                    delivery_address=item.get('delivery_address', '13316'),
                    delivery_date=delivery_date
                )

            jobs_by_delivery[delivery_key].lines.append(StockJobLine(
                part_number=item['part_number'],
                quantity=item.get('quantity', 500),
                price=item.get('price', 100.00)
            ))

        jobs = list(jobs_by_delivery.values())

        # Generate XML
        filepath, count = xml_gen.generate_stock_jobs(jobs, output_folder)

        # Log the generation
        logger.log_job_created(
            "STOCK",
            items[0]['part_number'] if len(items) == 1 else f"{len(items)} parts",
            sum(item.get('quantity', 0) for item in items),
            Path(filepath).name
        )

        return jsonify({
            "success": True,
            "filepath": filepath,
            "filename": Path(filepath).name,
            "order_count": count,
            "total_quantity": sum(item.get('quantity', 0) for item in items)
        })

    except Exception as e:
        logger.log_error("XML Generation", f"Stock job generation failed: {str(e)}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/xml/generate/movements', methods=['POST'])
def generate_movements():
    """
    Generate stock movement XML.

    Request body:
    {
        "items": [
            {
                "po_number": "BL020320",
                "item_code": "2029033",
                "job_number": "7755514",
                "quantity": 12500,
                "price": 50,
                "delivery_address": "16291",
                "delivery_date": "2026-01-08",
                "crif_date": "2026-01-06",
                "use_wip": false
            }
        ],
        "output_folder": "/path/to/output" (optional)
    }
    """
    data = request.get_json()
    logger = get_logger()
    config_service = get_config()
    xml_gen = get_xml_generator()

    items = data.get('items', [])
    if not items:
        return jsonify({"error": "No items provided"}), 400

    # Get output folder
    output_folder = data.get('output_folder') or config_service.config.xml_output_folder
    if not output_folder:
        output_folder = str(OUTPUTS_DIR / "xml")

    try:
        # Group items by PO number into movements
        movements_by_po = {}
        for item in items:
            po_num = item.get('po_number', 'UNKNOWN')
            if po_num not in movements_by_po:
                delivery_date = None
                crif_date = None
                if item.get('delivery_date'):
                    try:
                        delivery_date = datetime.strptime(item['delivery_date'], '%Y-%m-%d')
                    except ValueError:
                        pass
                if item.get('crif_date'):
                    try:
                        crif_date = datetime.strptime(item['crif_date'], '%Y-%m-%d')
                    except ValueError:
                        pass

                movements_by_po[po_num] = StockMovement(
                    po_number=po_num,
                    lines=[],
                    delivery_address=item.get('delivery_address', '16291'),
                    delivery_date=delivery_date,
                    crif_date=crif_date
                )

            movements_by_po[po_num].lines.append(MovementLine(
                item_code=item.get('item_code', ''),
                job_number=item.get('job_number', ''),
                quantity=item.get('quantity', 0),
                price=item.get('price', 50),
                use_wip=item.get('use_wip', False)
            ))

        movements = list(movements_by_po.values())

        # Generate XML
        filepath, count = xml_gen.generate_movements(movements, output_folder)

        # Log the generation
        logger.log_job_created(
            "MOVEMENT",
            items[0].get('item_code', '') if len(items) == 1 else f"{len(items)} items",
            sum(item.get('quantity', 0) for item in items),
            Path(filepath).name
        )

        return jsonify({
            "success": True,
            "filepath": filepath,
            "filename": Path(filepath).name,
            "order_count": count,
            "total_quantity": sum(item.get('quantity', 0) for item in items)
        })

    except Exception as e:
        logger.log_error("XML Generation", f"Movement generation failed: {str(e)}")
        return jsonify({"error": str(e)}), 500


@app.route('/api/xml/generate/from-comparison', methods=['POST'])
def generate_from_comparison():
    """
    Generate XML files based on comparison results.

    Automatically creates:
    - Stock movements for items that can be fulfilled from inventory
    - Stock/Rush jobs for items that need production

    Request body:
    {
        "output_folder": "/path/to/output" (optional),
        "selected_items": [indices] (optional - if not provided, processes all)
    }
    """
    if not app_state["po_data"]:
        return jsonify({"error": "No PO data loaded"}), 404

    data = request.get_json() or {}
    logger = get_logger()
    config_service = get_config()
    xml_gen = get_xml_generator()
    sql_service = get_sql_service()

    # Get output folder
    output_folder = data.get('output_folder') or config_service.config.xml_output_folder
    if not output_folder:
        output_folder = str(OUTPUTS_DIR / "xml")

    pos = app_state["po_data"]
    forecast = app_state["forecast_data"]
    all_details = get_all_details(pos)

    selected_indices = data.get('selected_items')
    if selected_indices:
        all_details = [all_details[i] for i in selected_indices if i < len(all_details)]

    # Categorize items
    stock_job_items = []
    movement_items = []

    for detail in all_details:
        # Get forecast
        forecast_qty = 0
        if forecast:
            forecast_record = forecast.get_by_part_and_site(detail.part_number, detail.site_code)
            if not forecast_record:
                matches = forecast.get_by_part(detail.part_number)
                if matches:
                    forecast_record = matches[0]
            if forecast_record:
                forecast_qty = forecast_record.get_current_month_forecast()
                if forecast_qty == 0:
                    forecast_qty = forecast_record.yearly_sum / 12

        # Check inventory coverage
        coverage = sql_service.check_inventory_coverage(
            part_number=detail.part_number,
            site=detail.site_code,
            order_qty=detail.quantity,  # Use exact quantity for movements
            forecast_qty=round(forecast_qty)
        )

        if coverage['action'] == 'movement':
            movement_items.append({
                'po_number': detail.po_number,
                'item_code': coverage.get('item_code', ''),
                'job_number': coverage.get('job_number', ''),
                'quantity': detail.quantity,  # Exact quantity for movements
                'price': coverage.get('price', 50),
                'delivery_date': detail.due_date.strftime('%Y-%m-%d'),
                'use_wip': coverage.get('source') == 'wip'
            })
        else:
            # Stock or Rush job - use rounded quantity
            stock_job_items.append({
                'part_number': detail.part_number,
                'quantity': detail.quantity_rounded,  # Rounded for jobs
                'price': detail.unit_price * 1000 if detail.unit_price else 100.00,
                'delivery_date': detail.due_date.strftime('%Y-%m-%d')
            })

    results = {
        "stock_jobs": None,
        "movements": None,
        "summary": {
            "stock_job_count": len(stock_job_items),
            "movement_count": len(movement_items)
        }
    }

    try:
        # Generate stock jobs if any
        if stock_job_items:
            filepath, count = xml_gen.generate_stock_jobs(
                [StockJob(lines=[
                    StockJobLine(
                        part_number=item['part_number'],
                        quantity=item['quantity'],
                        price=item['price']
                    ) for item in stock_job_items
                ])],
                output_folder
            )
            results["stock_jobs"] = {
                "filepath": filepath,
                "filename": Path(filepath).name,
                "order_count": count
            }
            logger.log_job_created("STOCK", f"{count} orders",
                                   sum(i['quantity'] for i in stock_job_items),
                                   Path(filepath).name)

        # Generate movements if any
        if movement_items:
            # Group by PO
            movements_by_po = {}
            for item in movement_items:
                po = item['po_number']
                if po not in movements_by_po:
                    movements_by_po[po] = []
                movements_by_po[po].append(item)

            movements = []
            for po_num, items in movements_by_po.items():
                movements.append(StockMovement(
                    po_number=po_num,
                    lines=[MovementLine(
                        item_code=item['item_code'],
                        job_number=item['job_number'],
                        quantity=item['quantity'],
                        price=item['price'],
                        use_wip=item['use_wip']
                    ) for item in items]
                ))

            filepath, count = xml_gen.generate_movements(movements, output_folder)
            results["movements"] = {
                "filepath": filepath,
                "filename": Path(filepath).name,
                "order_count": count
            }
            logger.log_job_created("MOVEMENT", f"{count} orders",
                                   sum(i['quantity'] for i in movement_items),
                                   Path(filepath).name)

        return jsonify({
            "success": True,
            **results
        })

    except Exception as e:
        logger.log_error("XML Generation", f"Generation from comparison failed: {str(e)}")
        return jsonify({"error": str(e)}), 500


# ============== MANUAL PROCESSING ==============

@app.route('/api/process/run', methods=['POST'])
def manual_process_run():
    """Manually trigger hot folder processing"""
    logger = get_logger()

    try:
        result = process_hot_folder(is_retry=False)
        app_state["last_run_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        return jsonify({
            "success": True,
            "message": result
        })
    except Exception as e:
        logger.log_error("Manual Processing", str(e))
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


# ============== SCHEDULED TASKS ==============

def delete_processed_file(source_path: Path) -> bool:
    """
    Delete a processed PO file after successful ingestion.
    Returns True if successful.
    """
    try:
        source_path.unlink()
        logger = get_logger()
        logger.log_user_action("File deleted after processing", source_path.name)
        return True
    except Exception as e:
        logger = get_logger()
        logger.log_error("Delete", f"Failed to delete {source_path.name}: {str(e)}")
        return False


def check_and_reload_forecast() -> tuple:
    """
    Check if forecast file has changed and reload if needed.

    Returns:
        (reloaded: bool, message: str)
    """
    config_service = get_config()
    logger = get_logger()

    if not config_service.is_forecast_folder_configured():
        return False, "Forecast folder not configured"

    has_changed, latest_file, reason = config_service.has_forecast_changed()

    if not has_changed:
        return False, reason

    if not latest_file:
        return False, "No forecast file found"

    # Reload the forecast
    logger.log_user_action("Forecast change detected", reason)

    forecast_data, errors = parse_forecast_file(str(latest_file))

    if forecast_data:
        app_state["forecast_data"] = forecast_data
        app_state["forecast_file"] = latest_file.name

        # Update tracking
        config_service.update_forecast_tracking(
            latest_file.name,
            latest_file.stat().st_mtime
        )

        logger.log_file_processed(latest_file.name, len(forecast_data.records), len(errors))
        logger.log_user_action("Forecast reloaded", f"{len(forecast_data.records)} records")

        return True, f"Loaded {latest_file.name} with {len(forecast_data.records)} records"
    else:
        logger.log_error("Forecast Reload", f"Failed to parse {latest_file.name}", str(errors))
        return False, f"Failed to parse: {errors}"


def process_hot_folder(is_retry: bool = False) -> str:
    """
    Process files in hot folder - called by scheduler at 7:00 AM ET daily.

    This function:
    1. Checks for and reloads updated forecast if changed
    2. Scans hot folder for new .txt PO files
    3. Parses each file
    4. Records orders for cumulative tracking
    5. Compares cumulative monthly orders against forecast
    6. Generates alerts and logs
    7. Deletes processed files after successful ingestion

    If no files found and not a retry, schedules a retry for 1 hour later.
    If retry also fails, issues an alert.

    Returns a status message.
    """
    logger = get_logger()
    config_service = get_config()
    order_tracker = get_order_tracker()

    now = datetime.now()
    current_year = now.year
    current_month = now.month

    # Check for forecast updates before processing
    forecast_reloaded, forecast_msg = check_and_reload_forecast()
    if forecast_reloaded:
        logger.log_user_action("Forecast auto-reloaded", forecast_msg)

    # Determine which folder to use
    if config_service.is_po_folder_configured():
        po_folder = Path(config_service.config.po_folder)
    else:
        po_folder = INPUTS_DIR

    logger.log_user_action("Hot folder processing started", str(po_folder))

    # Find all .txt files
    txt_files = list(po_folder.glob("*.txt"))

    if not txt_files:
        if is_retry:
            # Retry also failed - issue alert
            logger.log_alert(
                "Hot Folder Empty",
                None,
                "No PO files found after retry",
                f"Folder: {po_folder}"
            )
            logger.log_error("Hot Folder", "No files found after retry - alert issued")
            return "No files found after retry - alert issued"
        else:
            # Schedule retry for 1 hour later
            app_state["retry_scheduled"] = True
            logger.log_user_action("Hot folder empty", "Retry scheduled for 1 hour later")
            return "No files found - retry scheduled for 1 hour"

    # Reset retry flag since we found files
    app_state["retry_scheduled"] = False

    processed_count = 0
    error_count = 0

    for txt_file in txt_files:
        try:
            # Parse PO file
            pos, errors = parse_po_file(str(txt_file))

            if pos:
                all_details = get_all_details(pos)
                app_state["po_data"] = pos
                app_state["po_file"] = txt_file.name

                # Check if this PO was already recorded (prevent double-counting)
                po_numbers = list(set(d.po_number for d in all_details))
                already_recorded = any(
                    order_tracker.is_po_already_recorded(po) for po in po_numbers
                )

                if already_recorded:
                    logger.log_user_action("PO already processed", f"Skipping duplicate: {po_numbers}")
                else:
                    # Record all orders for cumulative tracking
                    for detail in all_details:
                        order_tracker.record_order(
                            po_number=detail.po_number,
                            part_number=detail.part_number,
                            site=detail.site_code,
                            quantity=detail.quantity,
                            quantity_rounded=detail.quantity_rounded,
                            timestamp=now
                        )

                logger.log_file_processed(txt_file.name, len(all_details), len(errors))

                # Generate comparison alerts using CUMULATIVE monthly totals
                if app_state["forecast_data"]:
                    alerts = []
                    checked_parts = set()  # Only alert once per part+site

                    for detail in all_details:
                        check_key = f"{detail.part_number}|{detail.site_code}"
                        if check_key in checked_parts:
                            continue
                        checked_parts.add(check_key)

                        # Get forecast
                        forecast_record = app_state["forecast_data"].get_by_part_and_site(
                            detail.part_number, detail.site_code
                        )
                        if not forecast_record:
                            matches = app_state["forecast_data"].get_by_part(detail.part_number)
                            if matches:
                                forecast_record = matches[0]

                        forecast_qty = 0
                        if forecast_record:
                            forecast_qty = forecast_record.get_current_month_forecast()
                            if forecast_qty == 0:
                                forecast_qty = forecast_record.yearly_sum / 12

                        # Get CUMULATIVE orders for this month
                        _, cumulative_rounded = order_tracker.get_cumulative_by_part_site(
                            current_year, current_month, detail.part_number, detail.site_code
                        )

                        # Check if cumulative exceeds forecast
                        if cumulative_rounded > forecast_qty and forecast_qty > 0:
                            overage = cumulative_rounded - forecast_qty
                            logger.log_alert(
                                "Exceeds Monthly Forecast",
                                detail.part_number,
                                f"Cumulative ({cumulative_rounded:,}) > Forecast ({forecast_qty:,.0f}) by {overage:,}",
                                f"Site: {detail.site_code}, Month: {current_year}-{current_month:02d}"
                            )
                            alerts.append({
                                "type": "exceeds_forecast",
                                "part": detail.part_number,
                                "site": detail.site_code,
                                "cumulative": cumulative_rounded,
                                "forecast": forecast_qty,
                                "overage": overage
                            })

                    app_state["alerts"] = alerts

                # Delete the processed file after successful ingestion
                delete_processed_file(txt_file)
                processed_count += 1

            else:
                logger.log_error("File Processing", f"Failed to parse {txt_file.name}", str(errors))
                error_count += 1

        except Exception as e:
            logger.log_error("File Processing", f"Error processing {txt_file.name}", str(e))
            error_count += 1

    result_msg = f"Processed {processed_count} files, {error_count} errors"
    logger.log_user_action("Hot folder processing completed", result_msg)

    return result_msg


def check_retry_needed() -> bool:
    """Check if a retry is scheduled and due. Called by scheduler."""
    return app_state.get("retry_scheduled", False)


def execute_retry():
    """Execute the scheduled retry."""
    logger = get_logger()
    logger.log_user_action("Executing scheduled retry", "1 hour after empty hot folder")

    app_state["retry_scheduled"] = False
    result = process_hot_folder(is_retry=True)
    app_state["last_run_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    return result


# ============== MAIN ==============

def create_app():
    """Factory function for creating the app"""
    return app


if __name__ == '__main__':
    print("=" * 60)
    print("MCC Packaging Automation Middleware")
    print("=" * 60)
    print(f"Base directory: {BASE_DIR}")
    print(f"Inputs: {INPUTS_DIR}")
    print(f"Outputs: {OUTPUTS_DIR}")
    print("")
    print("Starting server at http://localhost:5000")
    print("=" * 60)

    app.run(debug=True, host='localhost', port=5000)
