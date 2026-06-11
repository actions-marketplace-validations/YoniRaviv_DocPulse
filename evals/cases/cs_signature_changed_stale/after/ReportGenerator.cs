namespace App.Reports;

public class ReportGenerator
{
    /// <summary>
    /// Generates a report for the given date range in the requested format.
    /// </summary>
    /// <param name="startDate">Inclusive start of the reporting period.</param>
    /// <param name="endDate">Inclusive end of the reporting period.</param>
    /// <param name="format">Output format: "pdf" or "csv".</param>
    /// <returns>A byte array containing the rendered document.</returns>
    public byte[] GenerateReport(DateTime startDate, DateTime endDate, string format = "pdf")
    {
        var data = _dataSource.Query(startDate, endDate);
        return format == "csv" ? _renderer.RenderCsv(data) : _renderer.RenderPdf(data);
    }
}
