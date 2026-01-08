"""
Excel Parser for Sherwin-Williams 52-Week Forecast Files

Parses .xlsx files containing forecast data by part number, site, and month.

File format:
- Row 0: Headers (Label Part #, Description, Site #, 52wk Sum, monthly columns)
- Row 1+: Data rows
- Column B: Label Part # (e.g., L-0000C1431-14CAN)
- Column C: Label Part Description
- Column D: Site # (e.g., 618, 658)
- Column E: 52wk Sum
- Columns F-S: Monthly forecasts (YYYYMM format in header)

Same part can appear multiple times for different sites.
"""

from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple
from pathlib import Path
from datetime import datetime
import pandas as pd


@dataclass
class ForecastRecord:
    """Single forecast record for a part at a specific site"""
    part_number: str
    description: str
    site: str
    yearly_sum: float
    monthly_forecasts: Dict[str, float] = field(default_factory=dict)

    def __str__(self):
        return f"{self.part_number} @ Site {self.site}: {self.yearly_sum:.0f}/yr"

    def get_forecast_for_month(self, year: int, month: int) -> float:
        """Get forecast for specific month (returns 0 if not found)"""
        key = f"{year}{month:02d}"
        return self.monthly_forecasts.get(key, 0.0)

    def get_current_month_forecast(self) -> float:
        """Get forecast for current month"""
        now = datetime.now()
        return self.get_forecast_for_month(now.year, now.month)

    def get_next_month_forecast(self) -> float:
        """Get forecast for next month"""
        now = datetime.now()
        month = now.month + 1
        year = now.year
        if month > 12:
            month = 1
            year += 1
        return self.get_forecast_for_month(year, month)

    @property
    def total_monthly_forecast(self) -> float:
        """Sum of all monthly forecasts"""
        return sum(self.monthly_forecasts.values())


@dataclass
class ForecastData:
    """Container for all forecast data from a file"""
    records: List[ForecastRecord]
    source_file: str
    loaded_at: datetime = field(default_factory=datetime.now)
    months_available: List[str] = field(default_factory=list)

    def __str__(self):
        return f"Forecast: {len(self.records)} records from {self.source_file}"

    def get_by_part(self, part_number: str) -> List[ForecastRecord]:
        """Get all records for a specific part number (may be multiple sites)"""
        return [r for r in self.records if r.part_number == part_number]

    def get_by_site(self, site: str) -> List[ForecastRecord]:
        """Get all records for a specific site"""
        site_str = str(site)
        return [r for r in self.records if str(r.site) == site_str]

    def get_by_part_and_site(self, part_number: str, site: str) -> Optional[ForecastRecord]:
        """Get specific record for part at site (should be unique)"""
        site_str = str(site)
        for r in self.records:
            if r.part_number == part_number and str(r.site) == site_str:
                return r
        return None

    def get_unique_parts(self) -> List[str]:
        """Get list of unique part numbers"""
        return sorted(set(r.part_number for r in self.records))

    def get_unique_sites(self) -> List[str]:
        """Get list of unique sites"""
        return sorted(set(str(r.site) for r in self.records))

    def search_parts(self, query: str) -> List[ForecastRecord]:
        """Search for parts containing query string"""
        query_upper = query.upper()
        return [r for r in self.records if query_upper in r.part_number.upper()]


def parse_forecast_file(file_path: str) -> Tuple[Optional[ForecastData], List[str]]:
    """
    Parse a forecast Excel file.

    Args:
        file_path: Path to the .xlsx file

    Returns:
        Tuple of (ForecastData or None, list of error messages)
    """
    errors: List[str] = []
    path = Path(file_path)

    if not path.exists():
        return None, [f"File not found: {file_path}"]

    try:
        # Read Excel file
        df = pd.read_excel(file_path, header=None)

        # Find header row (search first few rows for 'Label Part #')
        header_row_idx = None
        for idx in range(min(5, len(df))):
            row_vals = [str(v) if pd.notna(v) else '' for v in df.iloc[idx].tolist()]
            if any('Label Part' in v or 'Part #' in v for v in row_vals):
                header_row_idx = idx
                break

        if header_row_idx is None:
            # Default to row 1 if not found
            header_row_idx = 1

        header_row = df.iloc[header_row_idx].tolist()

        # Find key columns by content
        # Expected: [empty, 'Label Part #', 'Label Part Description', 'Site #', '52wk Sum', months...]
        part_col = None
        desc_col = None
        site_col = None
        sum_col = None
        month_cols = {}

        for idx, val in enumerate(header_row):
            if val is None:
                continue
            val_str = str(val).strip()

            if 'Label Part #' in val_str or 'Part #' in val_str:
                part_col = idx
            elif 'Description' in val_str:
                desc_col = idx
            elif 'Site' in val_str:
                site_col = idx
            elif '52wk' in val_str or 'Sum' in val_str:
                sum_col = idx
            elif val_str.replace('.', '').isdigit() and len(val_str.replace('.', '')) >= 6:
                # Monthly column (YYYYMM format, might have decimal like 202509.000000)
                month_key = val_str.split('.')[0]  # Remove decimal part
                if len(month_key) == 6:
                    month_cols[idx] = month_key

        # Validate we found required columns
        if part_col is None:
            errors.append("Could not find 'Label Part #' column")
            return None, errors
        if site_col is None:
            errors.append("Could not find 'Site #' column")
            return None, errors

        # Parse data rows (skip header row)
        records: List[ForecastRecord] = []
        months_available = sorted(month_cols.values())

        for row_idx in range(header_row_idx + 1, len(df)):
            row = df.iloc[row_idx]

            # Get part number
            part_val = row.iloc[part_col] if part_col < len(row) else None
            if pd.isna(part_val) or str(part_val).strip() == '':
                continue  # Skip empty rows

            part_number = str(part_val).strip()

            # Get description
            description = ""
            if desc_col is not None and desc_col < len(row):
                desc_val = row.iloc[desc_col]
                if not pd.isna(desc_val):
                    description = str(desc_val).strip()

            # Get site
            site_val = row.iloc[site_col] if site_col < len(row) else None
            site = str(int(site_val)) if pd.notna(site_val) and isinstance(site_val, (int, float)) else str(site_val or "")

            # Get yearly sum
            yearly_sum = 0.0
            if sum_col is not None and sum_col < len(row):
                sum_val = row.iloc[sum_col]
                if pd.notna(sum_val):
                    try:
                        yearly_sum = float(sum_val)
                    except (ValueError, TypeError):
                        pass

            # Get monthly forecasts
            monthly = {}
            for col_idx, month_key in month_cols.items():
                if col_idx < len(row):
                    val = row.iloc[col_idx]
                    if pd.notna(val):
                        try:
                            # Filter out very small values (often just 0.0001 placeholders)
                            fval = float(val)
                            if fval > 0.01:  # Only count meaningful values
                                monthly[month_key] = fval
                        except (ValueError, TypeError):
                            pass

            record = ForecastRecord(
                part_number=part_number,
                description=description,
                site=site,
                yearly_sum=yearly_sum,
                monthly_forecasts=monthly
            )
            records.append(record)

        forecast_data = ForecastData(
            records=records,
            source_file=str(path.name),
            months_available=months_available
        )

        return forecast_data, errors

    except Exception as e:
        errors.append(f"Error reading file: {str(e)}")
        return None, errors


def find_matching_forecast(
    forecast_data: ForecastData,
    part_number: str,
    site: Optional[str] = None
) -> Optional[ForecastRecord]:
    """
    Find forecast for a part, optionally filtered by site.

    If site is provided, returns exact match.
    If no site, returns first matching part (useful when site mapping isn't clear).
    """
    if site:
        return forecast_data.get_by_part_and_site(part_number, site)
    else:
        matches = forecast_data.get_by_part(part_number)
        return matches[0] if matches else None


# CLI testing
if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        file_path = sys.argv[1]
    else:
        file_path = "inputs/MCC 52wk Fcst_261_1387993731861631085 (1).xlsx"

    print(f"Parsing: {file_path}")
    print("-" * 60)

    forecast, errors = parse_forecast_file(file_path)

    if errors:
        print("Errors:")
        for e in errors:
            print(f"  {e}")

    if forecast:
        print(f"Loaded: {forecast}")
        print(f"Months available: {forecast.months_available}")
        print(f"Unique parts: {len(forecast.get_unique_parts())}")
        print(f"Unique sites: {forecast.get_unique_sites()}")

        print("\nFirst 10 records:")
        for r in forecast.records[:10]:
            print(f"  {r}")
            if r.monthly_forecasts:
                first_month = list(r.monthly_forecasts.items())[0]
                print(f"    Sample month {first_month[0]}: {first_month[1]:.0f}")

        # Test search
        print("\nSearch for 'A300':")
        results = forecast.search_parts("A300")
        for r in results[:5]:
            print(f"  {r}")
