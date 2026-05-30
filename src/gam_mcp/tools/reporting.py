"""Reporting tools for Google Ad Manager."""

import base64
import copy
import csv
import gzip
import io
import logging
import time
from typing import Any, List, Optional

from ..client import get_gam_client
from ..utils import safe_get, zeep_to_dict

logger = logging.getLogger(__name__)

# Common report dimensions, grouped by purpose. Values are passed through to the
# GAM ReportService as-is, so additions here are documentation/exposure only.
DIMENSIONS = {
    # Time
    "DATE": "DATE",
    "WEEK": "WEEK",
    "MONTH_AND_YEAR": "MONTH_AND_YEAR",
    # Order / line item / creative
    "ORDER_ID": "ORDER_ID",
    "ORDER_NAME": "ORDER_NAME",
    "LINE_ITEM_ID": "LINE_ITEM_ID",
    "LINE_ITEM_NAME": "LINE_ITEM_NAME",
    "LINE_ITEM_TYPE": "LINE_ITEM_TYPE",
    "CREATIVE_ID": "CREATIVE_ID",
    "CREATIVE_NAME": "CREATIVE_NAME",
    "CREATIVE_SIZE": "CREATIVE_SIZE",
    "ADVERTISER_ID": "ADVERTISER_ID",
    "ADVERTISER_NAME": "ADVERTISER_NAME",
    "AD_UNIT_ID": "AD_UNIT_ID",
    "AD_UNIT_NAME": "AD_UNIT_NAME",
    # Programmatic / yield-partner attribution (OpenBidding, Ad Exchange)
    "YIELD_PARTNER": "YIELD_PARTNER",
    "YIELD_PARTNER_TAG": "YIELD_PARTNER_TAG",
    "YIELD_GROUP_NAME": "YIELD_GROUP_NAME",
    "YIELD_GROUP_ID": "YIELD_GROUP_ID",
    "DEMAND_CHANNEL_NAME": "DEMAND_CHANNEL_NAME",
    "DEMAND_CHANNEL_ID": "DEMAND_CHANNEL_ID",
    "BUYER_NETWORK_NAME": "BUYER_NETWORK_NAME",
    "BIDDER_NAME": "BIDDER_NAME",
    "EXCHANGE_BIDDING_DEAL_TYPE": "EXCHANGE_BIDDING_DEAL_TYPE",
    "PROGRAMMATIC_BUYER_NAME": "PROGRAMMATIC_BUYER_NAME",
    # Geo / device / app
    "COUNTRY_NAME": "COUNTRY_NAME",
    "COUNTRY_CRITERIA_ID": "COUNTRY_CRITERIA_ID",
    "DEVICE_CATEGORY_NAME": "DEVICE_CATEGORY_NAME",
    "OPERATING_SYSTEM_VERSION_NAME": "OPERATING_SYSTEM_VERSION_NAME",
    "BROWSER_NAME": "BROWSER_NAME",
    "MOBILE_APP_NAME": "MOBILE_APP_NAME",
    "REQUESTED_AD_SIZES": "REQUESTED_AD_SIZES",
}

# Common report metrics (columns). Values are pass-through to GAM ReportService.
METRICS = {
    # Line-item-level totals
    "TOTAL_LINE_ITEM_LEVEL_IMPRESSIONS": "TOTAL_LINE_ITEM_LEVEL_IMPRESSIONS",
    "TOTAL_LINE_ITEM_LEVEL_CLICKS": "TOTAL_LINE_ITEM_LEVEL_CLICKS",
    "TOTAL_LINE_ITEM_LEVEL_CTR": "TOTAL_LINE_ITEM_LEVEL_CTR",
    "TOTAL_LINE_ITEM_LEVEL_CPM_AND_CPC_REVENUE": "TOTAL_LINE_ITEM_LEVEL_CPM_AND_CPC_REVENUE",
    "TOTAL_LINE_ITEM_LEVEL_ALL_REVENUE": "TOTAL_LINE_ITEM_LEVEL_ALL_REVENUE",
    "TOTAL_LINE_ITEM_LEVEL_WITH_CPD_AVERAGE_ECPM": "TOTAL_LINE_ITEM_LEVEL_WITH_CPD_AVERAGE_ECPM",
    # Inventory-level totals
    "TOTAL_INVENTORY_LEVEL_IMPRESSIONS": "TOTAL_INVENTORY_LEVEL_IMPRESSIONS",
    "TOTAL_AD_REQUESTS": "TOTAL_AD_REQUESTS",
    "TOTAL_RESPONSES_SERVED": "TOTAL_RESPONSES_SERVED",
    "TOTAL_FILL_RATE": "TOTAL_FILL_RATE",
    # Ad Exchange / OpenBidding revenue and auction
    "AD_EXCHANGE_LINE_ITEM_LEVEL_IMPRESSIONS": "AD_EXCHANGE_LINE_ITEM_LEVEL_IMPRESSIONS",
    "AD_EXCHANGE_LINE_ITEM_LEVEL_CLICKS": "AD_EXCHANGE_LINE_ITEM_LEVEL_CLICKS",
    "AD_EXCHANGE_LINE_ITEM_LEVEL_REVENUE": "AD_EXCHANGE_LINE_ITEM_LEVEL_REVENUE",
    # Yield-group / OpenBidding auction
    "YIELD_GROUP_ESTIMATED_CPM": "YIELD_GROUP_ESTIMATED_CPM",
    "YIELD_GROUP_IMPRESSIONS": "YIELD_GROUP_IMPRESSIONS",
    "YIELD_GROUP_CALLOUTS": "YIELD_GROUP_CALLOUTS",
    "YIELD_GROUP_SUCCESSFUL_RESPONSES": "YIELD_GROUP_SUCCESSFUL_RESPONSES",
}

# Date range types
DATE_RANGE_TYPES = {
    "TODAY": "TODAY",
    "YESTERDAY": "YESTERDAY",
    "LAST_WEEK": "LAST_WEEK",
    "LAST_MONTH": "LAST_MONTH",
    "LAST_3_MONTHS": "LAST_3_MONTHS",
    "REACH_LIFETIME": "REACH_LIFETIME",
    "CUSTOM_DATE": "CUSTOM_DATE",
}


def run_delivery_report(
    date_range_type: str = "LAST_WEEK",
    start_year: Optional[int] = None,
    start_month: Optional[int] = None,
    start_day: Optional[int] = None,
    end_year: Optional[int] = None,
    end_month: Optional[int] = None,
    end_day: Optional[int] = None,
    order_id: Optional[int] = None,
    line_item_id: Optional[int] = None,
    include_date_breakdown: bool = True,
    export_format: str = "CSV_DUMP",
    timeout_seconds: int = 120,
    network_code: Optional[str] = None
) -> dict:
    """Run a delivery report for orders and line items.

    This is a preset report that returns impressions, clicks, CTR, and revenue
    broken down by order and line item.

    Args:
        date_range_type: Date range for the report. Valid values:
            - TODAY, YESTERDAY, LAST_WEEK, LAST_MONTH, LAST_3_MONTHS, REACH_LIFETIME
            - CUSTOM_DATE (requires start and end date parameters)
        start_year: Start date year (required if date_range_type is CUSTOM_DATE)
        start_month: Start date month 1-12 (required if date_range_type is CUSTOM_DATE)
        start_day: Start date day 1-31 (required if date_range_type is CUSTOM_DATE)
        end_year: End date year (required if date_range_type is CUSTOM_DATE)
        end_month: End date month 1-12 (required if date_range_type is CUSTOM_DATE)
        end_day: End date day 1-31 (required if date_range_type is CUSTOM_DATE)
        order_id: Optional order ID to filter by
        line_item_id: Optional line item ID to filter by
        include_date_breakdown: If True, includes daily breakdown (default: True)
        export_format: Report export format, e.g. CSV_DUMP, TSV, XML, XLSX
        timeout_seconds: Maximum time to wait for report (default: 120)
        network_code: Optional GAM network code. Uses default if not provided.

    Returns:
        dict with report data including rows of delivery statistics
    """
    # Build dimensions
    dimensions = ["ORDER_ID", "ORDER_NAME", "LINE_ITEM_ID", "LINE_ITEM_NAME"]
    if include_date_breakdown:
        dimensions.insert(0, "DATE")

    # Build columns (metrics)
    columns = [
        "TOTAL_LINE_ITEM_LEVEL_IMPRESSIONS",
        "TOTAL_LINE_ITEM_LEVEL_CLICKS",
        "TOTAL_LINE_ITEM_LEVEL_CTR",
        "TOTAL_LINE_ITEM_LEVEL_ALL_REVENUE",
    ]

    # Build filter
    filter_statement = None
    if order_id:
        filter_statement = f"ORDER_ID = {order_id}"
    if line_item_id:
        if filter_statement:
            filter_statement += f" AND LINE_ITEM_ID = {line_item_id}"
        else:
            filter_statement = f"LINE_ITEM_ID = {line_item_id}"

    return run_custom_report(
        dimensions=dimensions,
        columns=columns,
        date_range_type=date_range_type,
        start_year=start_year,
        start_month=start_month,
        start_day=start_day,
        end_year=end_year,
        end_month=end_month,
        end_day=end_day,
        filter_statement=filter_statement,
        export_format=export_format,
        timeout_seconds=timeout_seconds,
        network_code=network_code
    )


def run_inventory_report(
    date_range_type: str = "LAST_WEEK",
    start_year: Optional[int] = None,
    start_month: Optional[int] = None,
    start_day: Optional[int] = None,
    end_year: Optional[int] = None,
    end_month: Optional[int] = None,
    end_day: Optional[int] = None,
    ad_unit_id: Optional[str] = None,
    include_date_breakdown: bool = True,
    export_format: str = "CSV_DUMP",
    timeout_seconds: int = 120,
    network_code: Optional[str] = None
) -> dict:
    """Run an inventory report for ad units.

    This is a preset report that returns ad requests, impressions, fill rate
    broken down by ad unit.

    Args:
        date_range_type: Date range for the report (TODAY, YESTERDAY, LAST_WEEK, etc.)
        start_year: Start date year (for CUSTOM_DATE)
        start_month: Start date month 1-12 (for CUSTOM_DATE)
        start_day: Start date day 1-31 (for CUSTOM_DATE)
        end_year: End date year (for CUSTOM_DATE)
        end_month: End date month 1-12 (for CUSTOM_DATE)
        end_day: End date day 1-31 (for CUSTOM_DATE)
        ad_unit_id: Optional ad unit ID to filter by
        include_date_breakdown: If True, includes daily breakdown (default: True)
        export_format: Report export format, e.g. CSV_DUMP, TSV, XML, XLSX
        timeout_seconds: Maximum time to wait for report (default: 120)
        network_code: Optional GAM network code. Uses default if not provided.

    Returns:
        dict with report data including rows of inventory statistics
    """
    dimensions = ["AD_UNIT_ID", "AD_UNIT_NAME"]
    if include_date_breakdown:
        dimensions.insert(0, "DATE")

    columns = [
        "TOTAL_AD_REQUESTS",
        "TOTAL_INVENTORY_LEVEL_IMPRESSIONS",
        "TOTAL_RESPONSES_SERVED",
        "TOTAL_FILL_RATE",
    ]

    filter_statement = None
    if ad_unit_id:
        filter_statement = f"AD_UNIT_ID = {ad_unit_id}"

    return run_custom_report(
        dimensions=dimensions,
        columns=columns,
        date_range_type=date_range_type,
        start_year=start_year,
        start_month=start_month,
        start_day=start_day,
        end_year=end_year,
        end_month=end_month,
        end_day=end_day,
        filter_statement=filter_statement,
        export_format=export_format,
        timeout_seconds=timeout_seconds,
        network_code=network_code
    )


def run_custom_report(
    dimensions: List[str],
    columns: List[str],
    date_range_type: str = "LAST_WEEK",
    start_year: Optional[int] = None,
    start_month: Optional[int] = None,
    start_day: Optional[int] = None,
    end_year: Optional[int] = None,
    end_month: Optional[int] = None,
    end_day: Optional[int] = None,
    filter_statement: Optional[str] = None,
    export_format: str = "CSV_DUMP",
    timeout_seconds: int = 120,
    network_code: Optional[str] = None
) -> dict:
    """Run a custom report with specified dimensions and metrics.

    Args:
        dimensions: List of dimension names (e.g., ["DATE", "ORDER_NAME", "LINE_ITEM_NAME"]).
            Common dimensions, grouped:
              Time: DATE, WEEK, MONTH_AND_YEAR
              Order / line item / creative: ORDER_ID, ORDER_NAME, LINE_ITEM_ID, LINE_ITEM_NAME,
                LINE_ITEM_TYPE, CREATIVE_ID, CREATIVE_NAME, CREATIVE_SIZE, ADVERTISER_ID,
                ADVERTISER_NAME, AD_UNIT_ID, AD_UNIT_NAME
              Programmatic / yield-partner (OpenBidding, Ad Exchange): YIELD_PARTNER,
                YIELD_PARTNER_TAG, YIELD_GROUP_NAME, YIELD_GROUP_ID, DEMAND_CHANNEL_NAME,
                DEMAND_CHANNEL_ID, BUYER_NETWORK_NAME, BIDDER_NAME,
                EXCHANGE_BIDDING_DEAL_TYPE, PROGRAMMATIC_BUYER_NAME
              Geo / device / app: COUNTRY_NAME, COUNTRY_CRITERIA_ID, DEVICE_CATEGORY_NAME,
                OPERATING_SYSTEM_VERSION_NAME, BROWSER_NAME, MOBILE_APP_NAME, REQUESTED_AD_SIZES
            Any other dimension accepted by the GAM ReportService API may also be passed.
        columns: List of metric/column names (e.g., ["TOTAL_LINE_ITEM_LEVEL_IMPRESSIONS"]).
            Common metrics, grouped:
              Line-item-level totals: TOTAL_LINE_ITEM_LEVEL_IMPRESSIONS,
                TOTAL_LINE_ITEM_LEVEL_CLICKS, TOTAL_LINE_ITEM_LEVEL_CTR,
                TOTAL_LINE_ITEM_LEVEL_CPM_AND_CPC_REVENUE, TOTAL_LINE_ITEM_LEVEL_ALL_REVENUE,
                TOTAL_LINE_ITEM_LEVEL_WITH_CPD_AVERAGE_ECPM
              Inventory-level totals: TOTAL_INVENTORY_LEVEL_IMPRESSIONS, TOTAL_AD_REQUESTS,
                TOTAL_RESPONSES_SERVED, TOTAL_FILL_RATE
              Ad Exchange / OpenBidding revenue: AD_EXCHANGE_LINE_ITEM_LEVEL_IMPRESSIONS,
                AD_EXCHANGE_LINE_ITEM_LEVEL_CLICKS, AD_EXCHANGE_LINE_ITEM_LEVEL_REVENUE
              Yield-group / OpenBidding auction: YIELD_GROUP_ESTIMATED_CPM,
                YIELD_GROUP_IMPRESSIONS, YIELD_GROUP_CALLOUTS, YIELD_GROUP_SUCCESSFUL_RESPONSES
        date_range_type: Date range type (TODAY, YESTERDAY, LAST_WEEK, LAST_MONTH,
            LAST_3_MONTHS, REACH_LIFETIME, CUSTOM_DATE)
        start_year: Start year for CUSTOM_DATE range
        start_month: Start month (1-12) for CUSTOM_DATE range
        start_day: Start day (1-31) for CUSTOM_DATE range
        end_year: End year for CUSTOM_DATE range
        end_month: End month (1-12) for CUSTOM_DATE range
        end_day: End day (1-31) for CUSTOM_DATE range
        filter_statement: Optional filter (e.g., "ORDER_ID = 12345")
        export_format: Report export format, e.g. CSV_DUMP, TSV, XML, XLSX
        timeout_seconds: Maximum seconds to wait for report completion
        network_code: Optional GAM network code. Uses default if not provided.

    Returns:
        dict with report data including column headers and data rows
    """
    report_result = start_custom_report(
        dimensions=dimensions,
        columns=columns,
        date_range_type=date_range_type,
        start_year=start_year,
        start_month=start_month,
        start_day=start_day,
        end_year=end_year,
        end_month=end_month,
        end_day=end_day,
        filter_statement=filter_statement,
        network_code=network_code,
    )
    if "error" in report_result:
        return report_result

    report_job_id = report_result["job_id"]
    wait_result = wait_for_report_job(
        report_job_id=report_job_id,
        timeout_seconds=timeout_seconds,
        network_code=network_code,
    )
    if "error" in wait_result:
        return wait_result

    download_result = download_report_data(
        report_job_id=report_job_id,
        export_format=export_format,
        network_code=network_code,
    )
    if "error" in download_result:
        return download_result

    result = {
        "success": True,
        "job_id": report_job_id,
        "date_range_type": date_range_type,
        "dimensions": dimensions,
        "columns": columns,
        "export_format": export_format,
    }
    result.update(download_result)
    if "row_count" in result:
        result["message"] = f"Report completed with {result['row_count']} data rows"
    else:
        result["message"] = "Report completed"
    return result


def start_custom_report(
    dimensions: List[str],
    columns: List[str],
    date_range_type: str = "LAST_WEEK",
    start_year: Optional[int] = None,
    start_month: Optional[int] = None,
    start_day: Optional[int] = None,
    end_year: Optional[int] = None,
    end_month: Optional[int] = None,
    end_day: Optional[int] = None,
    filter_statement: Optional[str] = None,
    network_code: Optional[str] = None,
) -> dict:
    """Start a custom report job and return immediately with the job ID."""
    report_query_or_error = _build_report_query(
        dimensions=dimensions,
        columns=columns,
        date_range_type=date_range_type,
        start_year=start_year,
        start_month=start_month,
        start_day=start_day,
        end_year=end_year,
        end_month=end_month,
        end_day=end_day,
        filter_statement=filter_statement,
    )
    if "error" in report_query_or_error:
        return report_query_or_error

    client = get_gam_client(network_code=network_code)
    report_service = client.get_service('ReportService')

    try:
        report_job = report_service.runReportJob(
            {'reportQuery': report_query_or_error}
        )
        report_job_id = safe_get(report_job, 'id')
        logger.info(f"Report job started with ID: {report_job_id}")
        return {
            "success": True,
            "job_id": report_job_id,
            "status": "STARTED",
            "date_range_type": date_range_type,
            "dimensions": dimensions,
            "columns": columns,
        }
    except Exception as e:
        logger.error(f"Error starting report: {e}")
        return {"error": f"Failed to start report: {str(e)}"}


def run_saved_query_report(
    saved_query_id: int,
    export_format: str = "CSV_DUMP",
    timeout_seconds: int = 120,
    date_range_type: Optional[str] = None,
    start_year: Optional[int] = None,
    start_month: Optional[int] = None,
    start_day: Optional[int] = None,
    end_year: Optional[int] = None,
    end_month: Optional[int] = None,
    end_day: Optional[int] = None,
    network_code: Optional[str] = None,
) -> dict:
    """Run a saved query report by saved query ID."""
    saved_query_result = get_saved_query(saved_query_id, network_code=network_code)
    if "error" in saved_query_result:
        return saved_query_result

    saved_query = saved_query_result["saved_query"]
    if saved_query.get("is_compatible_with_api_version") is False:
        return {
            "error": f"Saved query {saved_query_id} is not compatible with this API version"
        }

    report_query = copy.deepcopy(saved_query.get("report_query"))
    if not report_query:
        return {"error": f"Saved query {saved_query_id} does not include a report query"}

    if date_range_type:
        report_query["dateRangeType"] = date_range_type
        if date_range_type == "CUSTOM_DATE":
            if not all([start_year, start_month, start_day, end_year, end_month, end_day]):
                return {
                    "error": "CUSTOM_DATE requires start_year, start_month, start_day, "
                             "end_year, end_month, and end_day parameters"
                }
            report_query["startDate"] = {
                "year": start_year,
                "month": start_month,
                "day": start_day,
            }
            report_query["endDate"] = {
                "year": end_year,
                "month": end_month,
                "day": end_day,
            }

    client = get_gam_client(network_code=network_code)
    report_service = client.get_service('ReportService')

    try:
        report_job = report_service.runReportJob({'reportQuery': report_query})
        report_job_id = safe_get(report_job, 'id')
    except Exception as e:
        logger.error(f"Error starting saved query report: {e}")
        return {"error": f"Failed to start saved query report: {str(e)}"}

    wait_result = wait_for_report_job(
        report_job_id=report_job_id,
        timeout_seconds=timeout_seconds,
        network_code=network_code,
    )
    if "error" in wait_result:
        return wait_result

    download_result = download_report_data(
        report_job_id=report_job_id,
        export_format=export_format,
        network_code=network_code,
    )
    if "error" in download_result:
        return download_result

    result = {
        "success": True,
        "saved_query_id": saved_query_id,
        "saved_query_name": saved_query.get("name"),
        "job_id": report_job_id,
        "export_format": export_format,
    }
    result.update(download_result)
    return result


def list_saved_queries(
    limit: int = 50,
    name_contains: Optional[str] = None,
    include_incompatible: bool = False,
    network_code: Optional[str] = None,
) -> dict:
    """List saved report queries available in GAM."""
    client = get_gam_client(network_code=network_code)
    saved_query_service = client.get_service('SavedQueryService')

    conditions = []
    if not include_incompatible:
        conditions.append("isCompatibleWithApiVersion = true")
    if name_contains:
        conditions.append("name LIKE :name")

    statement = client.create_statement()
    if conditions:
        statement = statement.Where(" AND ".join(conditions))
    if name_contains:
        statement = statement.WithBindVariable("name", f"%{name_contains}%")
    statement = statement.Limit(limit)

    try:
        response = saved_query_service.getSavedQueriesByStatement(
            statement.ToStatement()
        )
    except Exception as e:
        logger.error(f"Error listing saved queries: {e}")
        return {"error": f"Failed to list saved queries: {str(e)}"}

    results = safe_get(response, 'results', []) or []
    saved_queries = [_serialize_saved_query(saved_query) for saved_query in results]
    return {
        "saved_queries": saved_queries,
        "total": len(saved_queries),
        "limit": limit,
    }


def get_saved_query(
    saved_query_id: int,
    network_code: Optional[str] = None,
) -> dict:
    """Get a saved report query by ID."""
    client = get_gam_client(network_code=network_code)
    saved_query_service = client.get_service('SavedQueryService')

    statement = client.create_statement()
    statement = statement.Where("id = :id").WithBindVariable("id", saved_query_id)

    try:
        response = saved_query_service.getSavedQueriesByStatement(
            statement.ToStatement()
        )
    except Exception as e:
        logger.error(f"Error getting saved query: {e}")
        return {"error": f"Failed to get saved query: {str(e)}"}

    results = safe_get(response, 'results', []) or []
    if not results:
        return {"error": f"Saved query {saved_query_id} not found"}

    return {"saved_query": _serialize_saved_query(results[0])}


def get_report_job_status(
    report_job_id: int,
    network_code: Optional[str] = None,
) -> dict:
    """Get the status of a report job."""
    client = get_gam_client(network_code=network_code)
    report_service = client.get_service('ReportService')

    try:
        status = report_service.getReportJobStatus(report_job_id)
        return {
            "job_id": report_job_id,
            "status": status,
            "is_terminal": status in {"COMPLETED", "FAILED"},
        }
    except Exception as e:
        logger.error(f"Error getting report job status: {e}")
        return {"error": f"Failed to get report job status: {str(e)}"}


def wait_for_report_job(
    report_job_id: int,
    timeout_seconds: int = 120,
    poll_interval_seconds: int = 2,
    network_code: Optional[str] = None,
) -> dict:
    """Wait for a report job to complete."""
    start_time = time.time()
    status = None

    while time.time() - start_time < timeout_seconds:
        status_result = get_report_job_status(
            report_job_id=report_job_id,
            network_code=network_code,
        )
        if "error" in status_result:
            return status_result

        status = status_result["status"]
        if status == 'COMPLETED':
            logger.info(f"Report job {report_job_id} completed")
            return {
                "success": True,
                "job_id": report_job_id,
                "status": status,
            }
        if status == 'FAILED':
            return {
                "error": "Report job failed",
                "job_id": report_job_id,
                "status": status,
            }

        time.sleep(poll_interval_seconds)

    return {
        "error": f"Report job timed out after {timeout_seconds} seconds",
        "job_id": report_job_id,
        "status": status,
    }


def get_report_download_url(
    report_job_id: int,
    export_format: str = "CSV_DUMP",
    use_gzip_compression: bool = True,
    network_code: Optional[str] = None,
) -> dict:
    """Get a download URL for a completed report job."""
    client = get_gam_client(network_code=network_code)
    downloader = client.get_data_downloader()

    try:
        if hasattr(downloader, "GetReportDownloadUrlWithOptions"):
            url = downloader.GetReportDownloadUrlWithOptions(
                report_job_id,
                export_format,
                {"useGzipCompression": use_gzip_compression},
            )
        else:
            url = downloader.GetReportDownloadUrl(report_job_id, export_format)
        return {
            "job_id": report_job_id,
            "export_format": export_format,
            "use_gzip_compression": use_gzip_compression,
            "download_url": url,
        }
    except Exception as e:
        logger.error(f"Error getting report download URL: {e}")
        return {"error": f"Failed to get report download URL: {str(e)}"}


def download_report_data(
    report_job_id: int,
    export_format: str = "CSV_DUMP",
    network_code: Optional[str] = None,
) -> dict:
    """Download report data for a completed report job."""
    client = get_gam_client(network_code=network_code)
    report_downloader = client.get_data_downloader()

    try:
        buffer = io.BytesIO()
        report_downloader.DownloadReportToFile(report_job_id, export_format, buffer)
        buffer.seek(0)
        content = buffer.read()

        try:
            content = gzip.decompress(content)
        except (gzip.BadGzipFile, OSError):
            pass

        text = content.decode('utf-8')
    except UnicodeDecodeError:
        return {
            "bytes_count": len(content),
            "content_base64": base64.b64encode(content).decode("utf-8"),
            "encoding": "base64",
        }
    except Exception as e:
        logger.error(f"Error downloading report: {e}")
        return {"error": f"Failed to download report: {str(e)}"}

    delimiter = "\t" if export_format.startswith("TSV") else ","
    if export_format in {"CSV_DUMP", "TSV", "TSV_EXCEL"}:
        rows = _parse_delimited_report(text, delimiter=delimiter)
        return {
            "row_count": len(rows) - 1 if rows else 0,
            "headers": rows[0] if rows else [],
            "data": rows[1:] if rows else [],
        }

    return {
        "text": text,
        "bytes_count": len(text.encode("utf-8")),
    }


def _build_report_query(
    dimensions: List[str],
    columns: List[str],
    date_range_type: str,
    start_year: Optional[int] = None,
    start_month: Optional[int] = None,
    start_day: Optional[int] = None,
    end_year: Optional[int] = None,
    end_month: Optional[int] = None,
    end_day: Optional[int] = None,
    filter_statement: Optional[str] = None,
) -> dict:
    """Build a GAM report query dict or return an error dict."""
    if date_range_type == "CUSTOM_DATE":
        if not all([start_year, start_month, start_day, end_year, end_month, end_day]):
            return {
                "error": "CUSTOM_DATE requires start_year, start_month, start_day, "
                         "end_year, end_month, and end_day parameters"
            }

    report_query = {
        'dimensions': dimensions,
        'columns': columns,
        'dateRangeType': date_range_type,
    }

    if date_range_type == "CUSTOM_DATE":
        report_query['startDate'] = {
            'year': start_year,
            'month': start_month,
            'day': start_day
        }
        report_query['endDate'] = {
            'year': end_year,
            'month': end_month,
            'day': end_day
        }

    # Add filter if specified
    if filter_statement:
        report_query['statement'] = {
            'query': f"WHERE {filter_statement}"
        }

    return report_query


def _parse_delimited_report(report_data: str, delimiter: str = ",") -> List[List[str]]:
    """Parse delimited report data into rows.

    Args:
        report_data: Raw delimited string from report download
        delimiter: Field delimiter

    Returns:
        List of rows, where each row is a list of column values
    """
    reader = csv.reader(io.StringIO(report_data.strip()), delimiter=delimiter)
    return [row for row in reader if row]


def _serialize_saved_query(saved_query: Any) -> dict:
    """Convert a saved query SOAP object into JSON-friendly fields."""
    report_query = safe_get(saved_query, 'reportQuery')
    return {
        "id": safe_get(saved_query, 'id'),
        "name": safe_get(saved_query, 'name'),
        "is_compatible_with_api_version": safe_get(
            saved_query, 'isCompatibleWithApiVersion'
        ),
        "report_query": zeep_to_dict(report_query),
    }


def _parse_csv_report(report_data: str) -> List[List[str]]:
    """Backward-compatible CSV parser wrapper."""
    return _parse_delimited_report(report_data, delimiter=",")


def get_available_dimensions() -> dict:
    """Get list of available report dimensions.

    Returns:
        dict with available dimension names and descriptions
    """
    return {
        "dimensions": list(DIMENSIONS.keys()),
        "description": "Available dimensions for custom reports"
    }


def get_available_metrics() -> dict:
    """Get list of available report metrics (columns).

    Returns:
        dict with available metric names and descriptions
    """
    return {
        "metrics": list(METRICS.keys()),
        "description": "Available metrics/columns for custom reports"
    }
