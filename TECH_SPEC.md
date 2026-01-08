# Sherwin-Williams Packaging Automation Middleware
## Technical Specification Document

**Version:** 0.5 (Draft)
**Date:** 2026-01-06
**Status:** Requirements Gathering

---

## 1. Overview

This middleware system automates the creation of **stock jobs** and **rush jobs** for Sherwin-Williams packaging operations. The supplier plant produces labels to forecast; this system helps manage the gap between forecasted demand, actual orders, and available inventory.

### 1.1 Key Concepts

| Term | Definition |
|------|------------|
| **Stock Job** | Production job created from forecast data (planned production) |
| **Rush Job** | Production job created when inventory < order OR customer exceeds forecast |
| **Stock Movement** | Order to pull from existing inventory (no new production) |
| **Pack Size** | 500 units - ALL quantities rounded UP to nearest 500 |

---

## 2. Input File Formats

### 2.1 Forecast File (.xlsx)
**Source:** `MCC 52wk Fcst_261_1387993731861631085 (1).xlsx`
**Purpose:** 52-week forecast data for label parts - represents what the supplier plant produces TO

**Structure:**
| Column | Content | Example |
|--------|---------|---------|
| B | Label Part # | L-0000C1431-14CAN |
| C | Label Part Description | MLC CARE CAT LOW VOC |
| D | Site # | 618, 658, 638, etc. |
| E | 52wk Sum | Total annual forecast |
| F-S | Monthly forecasts | YYYYMM format (202509-202610) |

**Notes:**
- Row 0 contains headers
- Data starts at row 1
- ~10,346 rows of data
- Same label part can appear multiple times (different sites)

### 2.2 Purchase Order File (.txt)
**Source:** `qadp0961_7360_251030070105.txt`
**Purpose:** Daily purchase orders from hot folder - represents actual customer demand

**Structure:** Fixed-width format with two record types:

#### Header Record (H)
| Position | Length | Field | Example |
|----------|--------|-------|---------|
| 1-4 | 4 | Site Code | 45FL, HAQL, ECCL |
| 5-10 | 6 | PO Number | 907465, 008680 |
| 11 | 1 | Record Type | H |
| 12-17 | 6 | Date (MMDDYY) | 111925 |
| 18+ | Variable | Legacy fields | Ignored (status codes, buyer info) |

#### Detail Record (D)
| Position | Length | Field | Example |
|----------|--------|-------|---------|
| 1-4 | 4 | Site Code | 45FL |
| 5-10 | 6 | PO Number | 907465 |
| 11 | 1 | Record Type | D |
| 12-14 | 3 | Line Number | 1, 2, 10 |
| 15 | 1 | Prefix | L |
| 16-32 | ~17 | Part Number | -61370444-14 |
| ~33-38 | ~6 | Quantity | 5500 |
| 39-40 | 2 | UOM | EA |
| 41-51 | 11 | Unit Price | 00000.12690 |
| 52-61 | 10 | Due Date (MMDDYYYY) | 11/19/2025 |
| 72+ | Variable | Legacy fields | Ignored (trailing A, description) |

**Note:** Status codes (CLFDB, NEW, etc.) and trailing status indicators are legacy artifacts and are ignored.

---

## 3. Output XML Formats

### 3.1 Stock Job XML (sw-stock-MMDDYY#.xml)
**Purpose:** Create new production jobs from forecast
**DTD:** `http://www.fortdearborn.com/dtd/order-entry_1_1.dtd`

**Structure:**
```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE orders SYSTEM "http://www.fortdearborn.com/dtd/order-entry_1_1.dtd">
<orders>
  <order signal="submit" plant="14">
    <header>
      <order-customer address="12977" code="SHER003">
        <po>VMI MM.DD.YY ###</po>
      </order-customer>
      <invoice-customer address="12977"/>
      <delivery-customer address="13316" date="M/D/YYYY">
        <delivery-method code="TRK">
          <freight>
            <prepaid />
          </freight>
        </delivery-method>
      </delivery-customer>
      <request-options po-received="MM/DD/YYYY" crif="M/D/YYYY" crif-ship="M/D/YYYY" />
    </header>
    <lines>
      <line quantity="500" run-type="normal">
        <option>
          <book-stock-job price="100.00" price-qty="1000" />
        </option>
        <item>
          <customer-reference-number>L-PARTNUM-SIZE</customer-reference-number>
        </item>
      </line>
    </lines>
  </order>
</orders>
```

**Key Fields:**
| Field | Description | Source |
|-------|-------------|--------|
| `plant` | Always "14" | Constant |
| `order-customer code` | Always "SHER003" | Constant |
| `order-customer address` | Always "12977" | Constant |
| `po` | "VMI MM.DD.YY ###" (sequential) | Generated |
| `delivery-customer address` | Ship-to address | TBD - mapping needed |
| `delivery-customer date` | Delivery date | Calculated |
| `line quantity` | Order quantity (rounded to 500) | From forecast/order |
| `book-stock-job price` | Price per 1000 | From pricing data |
| `customer-reference-number` | Label part number | From forecast/PO |

### 3.2 Stock Movement XML (GT-Movement-MMDDYY-HHMMSS-###.xml)
**Purpose:** Pull from existing inventory (no new production needed)
**DTD:** `http://www.fortdearborn.com/dtd/order-entry_1_1.dtd`

**Structure:**
```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE orders SYSTEM "http://www.fortdearborn.com/dtd/order-entry_1_1.dtd">
<orders>
  <order signal="submit" plant="14">
    <header>
      <order-customer code="SHER003" address="12977">
        <po>PONUMBER</po>
        <ro>001</ro>
      </order-customer>
      <invoice-customer code="SHER003" address="12977"></invoice-customer>
      <delivery-customer code="SHER003" address="16291" date="MM/DD/YYYY">
        <delivery-method code="TRK">
          <freight>
            <collect />
          </freight>
        </delivery-method>
      </delivery-customer>
      <request-options po-received="MM/DD/YYYY" crif="MM/DD/YYYY" />
    </header>
    <lines>
      <line quantity="12500" run-type="normal">
        <option>
          <fail-if-insufficient-stock job-number="7755514" price="50" price-qty="1000" />
        </option>
        <item>
          <item-code>2029033</item-code>
        </item>
      </line>
    </lines>
  </order>
</orders>
```

**Key Differences from Stock Job:**
| Field | Stock Job | Stock Movement |
|-------|-----------|----------------|
| `po` | "VMI MM.DD.YY ###" | Original PO number |
| `ro` | Not present | Release order number (sequential) |
| `freight` | `<prepaid />` | `<collect />` |
| Option type | `<book-stock-job>` | `<fail-if-insufficient-stock>` or `<fail-if-insufficient-wip>` |
| Item identifier | `<customer-reference-number>` | `<item-code>` (internal code) |
| `job-number` | Not present | Existing job number to pull from |

### 3.3 Movement Option Types
| Option | Use Case |
|--------|----------|
| `fail-if-insufficient-stock` | Pull from finished goods inventory |
| `fail-if-insufficient-wip` | Pull from work-in-progress inventory |

---

## 4. System Functions

### 4.1 Primary View: Order vs Forecast vs Inventory Comparison

**This is the most important view.** Users need to see at a glance:

| Data Source | Represents |
|-------------|------------|
| Order Quantity (.txt) | What customer is actually ordering |
| Forecast (.xlsx) | What was predicted/planned |
| Inventory (SQL) | What is currently available |

**Alerts Generated When:**
- Order > Forecast (customer exceeding forecast)
- Order > Inventory (insufficient stock to fulfill)
- Inventory = 0 for ordered item

### 4.2 Stock Jobs (From Forecast)
**Trigger:** User-initiated from forecast data
**Purpose:** Planned production based on forecast
**Output:** Stock job XML with `<book-stock-job>` option

### 4.3 Rush Jobs (From Order Gaps)
**Trigger:** Automated when order cannot be fulfilled from inventory
**Purpose:** Emergency production when:
- Customer exceeds forecast
- Inventory insufficient for order
**Output:** Stock job XML (same format, flagged as rush?)

### 4.4 Stock Movements (Fulfill from Inventory)
**Trigger:** Order can be fulfilled from existing inventory
**Purpose:** Pull from stock without new production
**Output:** Movement XML with `<fail-if-insufficient-stock>` option

### 4.5 Job Overview Dashboard
Users need visibility into:
- Jobs created from forecast (stock jobs)
- Jobs created daily from orders (rush jobs)
- Stock movements processed
- Processing logs

### 4.6 SQL Query Executor
**Purpose:** Allow user to run existing SQL queries against the ERP database without needing to understand schema details.

**Features:**
- Text area for pasting SQL queries
- Execute button
- Results displayed in table format
- Export results to CSV (optional)
- Save frequently-used queries (optional)
- Query history

**Use Cases:**
- Look up `item-code` from part number
- Look up `job-number` for inventory movements
- Check inventory levels
- Verify pricing data
- Ad-hoc reporting

**Safety:**
- READ-ONLY queries only (SELECT statements)
- No INSERT, UPDATE, DELETE, DROP, etc.
- Query timeout limits

### 4.7 Logging & Audit Dashboard
**Purpose:** Track all system activity for review, troubleshooting, and audit trail.

**What Gets Logged:**
| Event Type | Details Captured |
|------------|------------------|
| File Processing | Timestamp, filename, records parsed, success/failure |
| Job Creation | Job type (stock/rush/movement), part number, quantity, XML filename |
| Alerts Generated | Alert type, part number, quantities involved |
| SQL Queries | Query text, execution time, row count, errors |
| Errors | Error type, message, stack trace, context |
| User Actions | File uploads, manual job triggers, exports |

**Log Storage:**
- **File-based only** (no database)
- Daily log files in `/outputs/logs/` folder
- CSV format for easy Excel viewing by GM
- Naming: `YYYY-MM-DD_activity.csv`
- Human-readable, audit-ready format
- Configurable retention period

**Dashboard Features:**
- View/filter by date range
- Filter by event type (jobs, alerts, errors, etc.)
- Filter by part number
- Search log messages
- Summary statistics (jobs created today, errors, etc.)
- Real-time log tail (live updates)

**Compliance/Audit Use:**
- GM can open CSV files directly in Excel for review
- Full history of all Sherwin-Williams transactions
- Tracks: what was ordered, what was produced, any discrepancies
- Exportable for compliance reporting

---

## 5. Business Rules

### 5.1 Quantity Rounding
**Stock Jobs and Rush Jobs** are rounded UP to nearest 500 (pack size).
**Stock Movements** use exact quantities (no rounding) since they pull from existing inventory.

| Output Type | Rounding |
|-------------|----------|
| Stock Job (from forecast) | Round UP to 500 |
| Rush Job (gap fill) | Round UP to 500 |
| Stock Movement (from inventory) | **Exact quantity** |

Examples for Jobs:
- Order: 501 → Job: 1000
- Order: 1000 → Job: 1000
- Order: 1001 → Job: 1500
- Order: 50 → Job: 500

Formula: `ceil(quantity / 500) * 500`

Examples for Movements:
- Order: 501 → Movement: 501
- Order: 1234 → Movement: 1234

### 5.2 Job Creation Logic

```
For each order line item:
  1. Get order quantity from PO
  2. Get forecast quantity for part/site/period
  3. Get current inventory from database

  IF inventory >= order_quantity:
      → Create STOCK MOVEMENT (pull from inventory)
  ELSE IF inventory > 0:
      → Create STOCK MOVEMENT for available inventory
      → Create RUSH JOB for (order_quantity - inventory), rounded to 500
  ELSE (inventory = 0):
      → Create RUSH JOB for order_quantity, rounded to 500

  IF order_quantity > forecast_quantity:
      → FLAG as "Exceeds Forecast" alert
```

### 5.3 Ignored Fields
- Header status codes (CLFDB, NEW, CEFDB, MOBUY02, etc.)
- Detail line trailing status (A)
- Buyer information in headers

---

## 6. Open Questions / Unknowns

### 6.1 XML Output Questions

| # | Question | Impact | Status |
|---|----------|--------|--------|
| Q1 | ~~What is the XML schema for stock job output?~~ | ~~Cannot generate output~~ | RESOLVED |
| Q2 | ~~What is the XML schema for movement output?~~ | ~~Cannot generate output~~ | RESOLVED |
| Q3 | Where should XML output files be placed? (hot folder path) | File path config | Needed |
| Q4 | ~~How to get `job-number` for movements?~~ | ~~Required for movement XML~~ | RESOLVED - from DB via SQL |
| Q5 | ~~How to get `item-code` (internal ID) from part number?~~ | ~~Required for movement XML~~ | RESOLVED - from DB via SQL |
| Q6 | What determines `prepaid` vs `collect` freight? | XML generation | Needed |
| Q7 | ~~How to determine delivery address code?~~ | ~~Address mapping~~ | RESOLVED - from PO data, multiple locations exist |
| Q8 | ~~What is price source?~~ | ~~XML generation~~ | RESOLVED - from ERP, not accurate (invoicing separate) |

### 6.2 Database Questions

| # | Question | Impact | Status |
|---|----------|--------|--------|
| Q9 | What database system? (SQL Server, MySQL, etc.) | Driver selection | BLOCKING |
| Q10 | Connection credentials/method? | Auth setup | BLOCKING |
| Q11 | ~~Inventory table schema?~~ | ~~Query construction~~ | User will provide SQL queries |
| Q12 | ~~How to join PO parts to inventory?~~ | ~~Match logic~~ | User will provide SQL queries |
| Q13 | ~~Where does `job-number` come from?~~ | ~~Movement generation~~ | User will provide SQL queries |
| Q14 | ~~Where does `item-code` come from?~~ | ~~Movement generation~~ | User will provide SQL queries |

**Note:** User will provide existing SQL queries to copy/paste into a SQL executor tool. This avoids needing to understand the full schema - we just need DB connection info.

### 6.3 Hot Folder Questions

| # | Question | Impact | Status |
|---|----------|--------|--------|
| Q15 | What is the hot folder input path for .txt files? | File watcher | Needed |
| Q16 | What is the hot folder output path for .xml files? | File output | Needed |
| Q17 | How often to poll? (seconds/minutes) | Performance | Default: 30s |

### 6.4 Business Logic Questions

| # | Question | Impact | Status |
|---|----------|--------|--------|
| Q18 | Part not in forecast - how to handle? | Error/alert handling | Needed |
| Q19 | Part not in inventory DB - how to handle? | Error/alert handling | Needed |
| Q20 | Site matching - is site code in .txt same as site # in .xlsx? | Join logic | Needed |
| Q21 | What period of forecast to compare? (current month? next month?) | Comparison logic | Needed |
| Q22 | Is there a difference in XML between stock job and rush job? | XML generation | Needed |

### 6.5 Resolved Questions

| # | Question | Answer |
|---|----------|--------|
| ~~Q~~ | Round quantities for jobs only or all? | ALL quantities rounded to 500 (pack size) |
| ~~Q~~ | Need logging? | Yes - logs folder + dashboard view |
| ~~Q~~ | Status code meaning? | Ignored - legacy artifact |
| ~~Q~~ | Trailing A meaning? | Ignored - legacy artifact |
| ~~Q~~ | XML schema for stock job? | See Section 3.1 |
| ~~Q~~ | XML schema for movement? | See Section 3.2 |

---

## 7. Proposed Architecture

```
┌──────────────────────────────────────────────────────────────────────┐
│                         LOCAL APPLICATION                             │
├──────────────────────────────────────────────────────────────────────┤
│  ┌────────────────────────────────────────────────────────────────┐  │
│  │                    HTML/CSS/JS Frontend                         │  │
│  │  ┌──────────────────────────────────────────────────────────┐  │  │
│  │  │              ORDER vs FORECAST vs INVENTORY               │  │  │
│  │  │                   (Primary View)                          │  │  │
│  │  │  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌────────────┐   │  │  │
│  │  │  │ Part #  │  │ Order   │  │Forecast │  │ Inventory  │   │  │  │
│  │  │  │         │  │  Qty    │  │   Qty   │  │    Qty     │   │  │  │
│  │  │  └─────────┘  └─────────┘  └─────────┘  └────────────┘   │  │  │
│  │  │                    [ALERTS PANEL]                         │  │  │
│  │  └──────────────────────────────────────────────────────────┘  │  │
│  │  ┌─────────────┐  ┌─────────────┐  ┌──────────────────────┐   │  │
│  │  │ Stock Jobs  │  │ Rush Jobs   │  │   Logs Dashboard     │   │  │
│  │  │  (Forecast) │  │ (Daily)     │  │                      │   │  │
│  │  └─────────────┘  └─────────────┘  └──────────────────────┘   │  │
│  │  ┌──────────────────────────────────────────────────────────┐   │  │
│  │  │                   SQL Query Executor                      │   │  │
│  │  │  [Paste SQL] → [Execute] → [Results Table] → [Export]     │   │  │
│  │  └──────────────────────────────────────────────────────────┘   │  │
│  └────────────────────────────────────────────────────────────────┘  │
│                                │                                      │
│                                ▼                                      │
│  ┌────────────────────────────────────────────────────────────────┐  │
│  │                   Python Backend (Flask)                        │  │
│  │  ┌──────────────┐ ┌──────────────┐ ┌────────────────────────┐  │  │
│  │  │ Excel Parser │ │  TXT Parser  │ │     XML Generator      │  │  │
│  │  │   (pandas)   │ │  (custom)    │ │   (stock/movement)     │  │  │
│  │  └──────────────┘ └──────────────┘ └────────────────────────┘  │  │
│  │  ┌──────────────┐ ┌──────────────┐ ┌────────────────────────┐  │  │
│  │  │  Inventory   │ │  Hot Folder  │ │   Comparison Engine    │  │  │
│  │  │   Query      │ │   Watcher    │ │  (order vs fcst vs inv)│  │  │
│  │  └──────────────┘ └──────────────┘ └────────────────────────┘  │  │
│  │  ┌────────────────────────────────────────────────────────┐    │  │
│  │  │                    Logging Service                      │    │  │
│  │  └────────────────────────────────────────────────────────┘    │  │
│  └────────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────────┘
         │                    │                    │
         ▼                    ▼                    ▼
┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐
│   Hot Folder    │  │  SQL Database   │  │   Output        │
│  (.txt input)   │  │  (Inventory)    │  │  ├── xml/       │
└─────────────────┘  └─────────────────┘  │  └── logs/      │
                                          └─────────────────┘
```

---

## 8. UI Wireframe Concepts

### 8.1 Main Dashboard - Comparison View

```
┌─────────────────────────────────────────────────────────────────────────┐
│  SHERWIN-WILLIAMS PACKAGING MIDDLEWARE                    [Upload xlsx] │
├─────────────────────────────────────────────────────────────────────────┤
│  ALERTS (3)                                                    [Clear]  │
│  ┌────────────────────────────────────────────────────────────────────┐ │
│  │ ⚠ L-61370444-14: Order (5500) exceeds forecast (3000)              │ │
│  │ ⚠ L-806150000-B-16: No inventory available                         │ │
│  │ ⚠ L-863054444-14: Order (11500) > Inventory (8000)                 │ │
│  └────────────────────────────────────────────────────────────────────┘ │
├─────────────────────────────────────────────────────────────────────────┤
│  ORDER vs FORECAST vs INVENTORY                     [Filter] [Search]   │
│  ┌────────────────────────────────────────────────────────────────────┐ │
│  │ Part #          │ Order │ Forecast │ Inventory │ Gap    │ Action   │ │
│  ├─────────────────┼───────┼──────────┼───────────┼────────┼──────────┤ │
│  │ L-61370444-14   │ 5500  │   3000   │   4000    │ -1500  │ Rush Job │ │
│  │ L-806150000-B   │  500  │    500   │      0    │  -500  │ Rush Job │ │
│  │ L-863054444-14  │ 11500 │  12000   │   8000    │ -3500  │ Rush Job │ │
│  │ L-S64T00050-14  │ 7500  │   8000   │  10000    │  OK    │ Movement │ │
│  └────────────────────────────────────────────────────────────────────┘ │
├─────────────────────────────────────────────────────────────────────────┤
│  [Stock Jobs]  [Rush Jobs]  [Movements]  [Logs]                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### 8.2 Jobs View

```
┌─────────────────────────────────────────────────────────────────────────┐
│  JOBS                                   [Stock Jobs] [Rush Jobs] [All]  │
├─────────────────────────────────────────────────────────────────────────┤
│  Today: 12 Stock | 3 Rush | 45 Movements                                │
│  ┌────────────────────────────────────────────────────────────────────┐ │
│  │ Type     │ Part #         │ Qty   │ Created  │ Status    │ XML     │ │
│  ├──────────┼────────────────┼───────┼──────────┼───────────┼─────────┤ │
│  │ Stock    │ L-0000C1431    │ 2000  │ 09:15 AM │ Generated │ [View]  │ │
│  │ Rush     │ L-61370444-14  │ 2000  │ 10:32 AM │ Generated │ [View]  │ │
│  │ Movement │ L-S64T00050-14 │ 7500  │ 10:32 AM │ Generated │ [View]  │ │
│  └────────────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────────┘
```

### 8.3 SQL Query Executor View

```
┌─────────────────────────────────────────────────────────────────────────┐
│  SQL QUERY EXECUTOR                                    [Saved Queries ▼]│
├─────────────────────────────────────────────────────────────────────────┤
│  ┌────────────────────────────────────────────────────────────────────┐ │
│  │ SELECT item_code, job_number, qty_on_hand                         │ │
│  │ FROM inventory                                                     │ │
│  │ WHERE part_number = 'L-61370444-14'                               │ │
│  │                                                                    │ │
│  └────────────────────────────────────────────────────────────────────┘ │
│                                          [Execute]  [Clear]  [Save As] │
├─────────────────────────────────────────────────────────────────────────┤
│  RESULTS (3 rows)                                        [Export CSV]   │
│  ┌────────────────────────────────────────────────────────────────────┐ │
│  │ item_code  │ job_number │ qty_on_hand │                            │ │
│  ├────────────┼────────────┼─────────────┤                            │ │
│  │ 2029033    │ 7755514    │ 15000       │                            │ │
│  │ 2029033    │ 7762740    │ 4500        │                            │ │
│  │ 2029033    │ 7771759    │ 8000        │                            │ │
│  └────────────────────────────────────────────────────────────────────┘ │
├─────────────────────────────────────────────────────────────────────────┤
│  Query executed in 0.23s                                                │
└─────────────────────────────────────────────────────────────────────────┘
```

### 8.4 Logs Dashboard View

```
┌─────────────────────────────────────────────────────────────────────────┐
│  LOGS DASHBOARD                                              [Export CSV]│
├─────────────────────────────────────────────────────────────────────────┤
│  Filters:                                                                │
│  Date: [01/06/2026 ▼] to [01/06/2026 ▼]   Type: [All ▼]   [Search...]   │
├─────────────────────────────────────────────────────────────────────────┤
│  TODAY'S SUMMARY                                                         │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐ ┌──────────────┐    │
│  │ Stock Jobs   │ │ Rush Jobs    │ │ Movements    │ │ Errors       │    │
│  │     12       │ │      3       │ │     45       │ │      0       │    │
│  └──────────────┘ └──────────────┘ └──────────────┘ └──────────────┘    │
├─────────────────────────────────────────────────────────────────────────┤
│  LOG ENTRIES                                               [Live Tail ●]│
│  ┌────────────────────────────────────────────────────────────────────┐ │
│  │ Timestamp        │ Type      │ Message                             │ │
│  ├──────────────────┼───────────┼─────────────────────────────────────┤ │
│  │ 10:32:15 AM      │ JOB       │ Rush job created: L-61370444-14     │ │
│  │                  │           │ Qty: 2000, XML: rush-010626-001.xml │ │
│  ├──────────────────┼───────────┼─────────────────────────────────────┤ │
│  │ 10:32:14 AM      │ ALERT     │ Order exceeds forecast: L-61370444  │ │
│  │                  │           │ Order: 5500, Forecast: 3000         │ │
│  ├──────────────────┼───────────┼─────────────────────────────────────┤ │
│  │ 10:32:10 AM      │ FILE      │ Processed: qadp0961_7360_251030.txt │ │
│  │                  │           │ 240 records parsed, 0 errors        │ │
│  ├──────────────────┼───────────┼─────────────────────────────────────┤ │
│  │ 10:30:00 AM      │ SQL       │ Query executed (0.23s, 3 rows)      │ │
│  │                  │           │ SELECT item_code FROM inventory...  │ │
│  └────────────────────────────────────────────────────────────────────┘ │
│                                               [< Prev]  Page 1  [Next >]│
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 9. Data Flow

### 9.1 Daily Automated Flow

```
.txt arrives in hot folder
         │
         ▼
    Parse PO data
         │
         ▼
    For each line item:
         │
    ┌────┴────────────────────────────┐
    │                                  │
    ▼                                  ▼
Get Forecast              Get Inventory + Job#/ItemCode
(from loaded .xlsx)       (SQL query)
    │                                  │
    └────────────┬─────────────────────┘
                 │
                 ▼
         ┌───────────────┐
         │   COMPARE     │
         │ Order vs Fcst │
         │ Order vs Inv  │
         └───────┬───────┘
                 │
    ┌────────────┼────────────┐
    │            │            │
    ▼            ▼            ▼
Order ≤ Inv  Order > Inv  Order > Fcst
    │            │            │
    ▼            ▼            ▼
MOVEMENT     MOVEMENT +    ALERT
  XML        RUSH JOB      (exceeds
             XML           forecast)
                 │
                 ▼
           Write XML + Log
```

---

## 10. Technology Stack

| Component | Technology | Justification |
|-----------|------------|---------------|
| Backend | Python 3.11+ | Requirement specified |
| Web Framework | Flask | Lightweight, simple for local use |
| Excel Parsing | pandas + openpyxl | Robust Excel handling |
| TXT Parsing | Custom fixed-width parser | Specific format handling |
| XML Generation | xml.etree.ElementTree | Standard library, sufficient |
| Database | pyodbc / pymssql | TBD based on DB type |
| File Watching | watchdog | Cross-platform file monitoring |
| Frontend | HTML/CSS/JavaScript | Requirement specified |
| UI Framework | Bootstrap 5 | Quick, professional styling |
| Logging | Python logging + CSV files | File-based, Excel-compatible |

---

## 11. File/Folder Structure (Proposed)

```
PAINT ON DEMAND/
├── app/
│   ├── __init__.py
│   ├── main.py              # Flask app entry point
│   ├── parsers/
│   │   ├── excel_parser.py  # Forecast xlsx parsing
│   │   └── txt_parser.py    # PO txt parsing
│   ├── services/
│   │   ├── database.py      # DB connection + SQL executor
│   │   ├── comparison.py    # Order vs Forecast vs Inventory
│   │   ├── job_generator.py # Stock job XML generation
│   │   ├── movement_generator.py # Movement XML generation
│   │   ├── watcher.py       # Hot folder monitoring
│   │   └── logger.py        # Logging service + SQLite storage
│   ├── models/
│   │   └── schemas.py       # Data classes
│   └── static/
│       ├── css/
│       ├── js/
│       └── index.html
├── inputs/                   # Input files (existing)
├── outputs/
│   ├── xml/                  # Generated job XMLs
│   └── logs/                 # Daily CSV logs (Excel-compatible)
│       ├── 2026-01-06_activity.csv
│       ├── 2026-01-05_activity.csv
│       └── ...
├── config.py                 # Configuration (paths, DB conn)
├── requirements.txt
└── TECH_SPEC.md
```

---

## 12. Next Steps

### Immediate (Blocking)
1. **Get database connection info** (type, server, credentials)

### Can Start Now
2. Build TXT parser
3. Build Excel parser
4. Build SQL executor UI
5. Build basic Flask UI skeleton
6. Build XML generators (stock job template ready)
7. Build comparison view UI

---

## 13. Assumptions

1. Single-user local application
2. TXT file format is consistent (fixed-width as analyzed)
3. One forecast file loaded at a time
4. Database accessible from local machine
5. Plant is always "14" for this customer
6. Customer code is always "SHER003"
7. Base address is always "12977"

---

## Appendix A: XML Field Reference

### A.1 Stock Job Fields
| XML Path | Value | Notes |
|----------|-------|-------|
| `order/@signal` | "submit" | Always submit |
| `order/@plant` | "14" | Constant |
| `order-customer/@code` | "SHER003" | Constant |
| `order-customer/@address` | "12977" | Constant |
| `order-customer/po` | "VMI MM.DD.YY ###" | Generated sequential |
| `invoice-customer/@address` | "12977" | Constant |
| `delivery-customer/@address` | Variable | Needs mapping |
| `delivery-customer/@date` | "M/D/YYYY" | Delivery date |
| `delivery-method/@code` | "TRK" | Truck delivery |
| `freight` | `<prepaid />` | For stock jobs |
| `request-options/@po-received` | "MM/DD/YYYY" | Order received date |
| `request-options/@crif` | "M/D/YYYY" | Customer requested date |
| `request-options/@crif-ship` | "M/D/YYYY" | Ship by date |
| `line/@quantity` | Integer | Rounded to 500 |
| `line/@run-type` | "normal" | Standard run |
| `book-stock-job/@price` | Decimal | Price per 1000 |
| `book-stock-job/@price-qty` | "1000" | Always 1000 |
| `customer-reference-number` | Part number | From forecast/PO |

### A.2 Movement Fields
| XML Path | Value | Notes |
|----------|-------|-------|
| `order-customer/po` | Original PO | From .txt file |
| `order-customer/ro` | "001", "002", etc. | Release order sequence |
| `delivery-customer/@code` | "SHER003" | Added for movements |
| `freight` | `<collect />` | For movements |
| `fail-if-insufficient-stock/@job-number` | Integer | Existing job to pull from |
| `fail-if-insufficient-stock/@price` | Integer | Price per 1000 |
| `fail-if-insufficient-stock/@price-qty` | "1000" | Always 1000 |
| `item-code` | Internal ID | From database |

---

## Revision History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 0.1 | 2026-01-06 | Claude | Initial draft |
| 0.2 | 2026-01-06 | Claude | Added business rules, job types, primary comparison view, alerts |
| 0.3 | 2026-01-06 | Claude | Added XML schema documentation from sample files, movement vs stock job differences, updated questions |
| 0.4 | 2026-01-06 | Claude | Added SQL Query Executor feature, resolved DB schema questions (user provides queries), clarified pricing/address handling |
| 0.5 | 2026-01-06 | Claude | Added detailed Logging & Audit Dashboard spec with wireframe, log event types, filtering, and export capabilities |
| 0.6 | 2026-01-06 | Claude | Changed logging to file-based CSV (no database), added GM/compliance review capability |
