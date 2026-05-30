"""Tests for reporting tools."""

import gzip
from unittest.mock import MagicMock, patch

from gam_mcp.tools import reporting


def _statement():
    statement = MagicMock()
    statement.Where.return_value = statement
    statement.WithBindVariable.return_value = statement
    statement.Limit.return_value = statement
    statement.ToStatement.return_value = {"query": "WHERE 1 = 1"}
    return statement


class TestReportLifecycle:
    """Tests for report job lifecycle helpers."""

    @patch("gam_mcp.tools.reporting.get_gam_client")
    def test_start_custom_report_returns_job_id(self, mock_get_client):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        report_service = MagicMock()
        report_service.runReportJob.return_value = {"id": 123}
        mock_client.get_service.return_value = report_service

        result = reporting.start_custom_report(
            dimensions=["DATE"],
            columns=["TOTAL_LINE_ITEM_LEVEL_IMPRESSIONS"],
        )

        assert result["job_id"] == 123
        assert result["status"] == "STARTED"
        report_service.runReportJob.assert_called_once()

    def test_start_custom_report_requires_custom_dates(self):
        result = reporting.start_custom_report(
            dimensions=["DATE"],
            columns=["TOTAL_LINE_ITEM_LEVEL_IMPRESSIONS"],
            date_range_type="CUSTOM_DATE",
        )

        assert "error" in result
        assert "CUSTOM_DATE requires" in result["error"]

    @patch("gam_mcp.tools.reporting.get_gam_client")
    def test_get_report_job_status(self, mock_get_client):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        report_service = MagicMock()
        report_service.getReportJobStatus.return_value = "COMPLETED"
        mock_client.get_service.return_value = report_service

        result = reporting.get_report_job_status(report_job_id=123)

        assert result["job_id"] == 123
        assert result["status"] == "COMPLETED"
        assert result["is_terminal"] is True

    @patch("gam_mcp.tools.reporting.get_gam_client")
    def test_get_report_download_url_with_options(self, mock_get_client):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        downloader = MagicMock()
        downloader.GetReportDownloadUrlWithOptions.return_value = "https://report"
        mock_client.get_data_downloader.return_value = downloader

        result = reporting.get_report_download_url(
            report_job_id=123,
            export_format="TSV",
            use_gzip_compression=False,
        )

        assert result["download_url"] == "https://report"
        downloader.GetReportDownloadUrlWithOptions.assert_called_once_with(
            123,
            "TSV",
            {"useGzipCompression": False},
        )


class TestReportDownload:
    """Tests for report download parsing."""

    @patch("gam_mcp.tools.reporting.get_gam_client")
    def test_download_report_data_parses_gzipped_csv(self, mock_get_client):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        def download(_job_id, _export_format, buffer):
            data = 'Name,Impressions\n"ACME, Inc.",100\n'.encode("utf-8")
            buffer.write(gzip.compress(data))

        downloader = MagicMock()
        downloader.DownloadReportToFile.side_effect = download
        mock_client.get_data_downloader.return_value = downloader

        result = reporting.download_report_data(report_job_id=123)

        assert result["row_count"] == 1
        assert result["headers"] == ["Name", "Impressions"]
        assert result["data"] == [["ACME, Inc.", "100"]]

    @patch("gam_mcp.tools.reporting.get_gam_client")
    def test_download_report_data_parses_tsv(self, mock_get_client):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        def download(_job_id, _export_format, buffer):
            buffer.write(b"Name\tImpressions\nACME\t100\n")

        downloader = MagicMock()
        downloader.DownloadReportToFile.side_effect = download
        mock_client.get_data_downloader.return_value = downloader

        result = reporting.download_report_data(report_job_id=123, export_format="TSV")

        assert result["headers"] == ["Name", "Impressions"]
        assert result["data"] == [["ACME", "100"]]


class TestSavedQueries:
    """Tests for saved query helpers."""

    @patch("gam_mcp.tools.reporting.get_gam_client")
    def test_list_saved_queries(self, mock_get_client):
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client
        mock_client.create_statement.return_value = _statement()

        saved_query_service = MagicMock()
        saved_query_service.getSavedQueriesByStatement.return_value = {
            "results": [{
                "id": 1,
                "name": "Delivery",
                "isCompatibleWithApiVersion": True,
                "reportQuery": {"dimensions": ["DATE"]},
            }]
        }
        mock_client.get_service.return_value = saved_query_service

        result = reporting.list_saved_queries(name_contains="Delivery")

        assert result["total"] == 1
        assert result["saved_queries"][0]["id"] == 1
        assert result["saved_queries"][0]["report_query"] == {"dimensions": ["DATE"]}
