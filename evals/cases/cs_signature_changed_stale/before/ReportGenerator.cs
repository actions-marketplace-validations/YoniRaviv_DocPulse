namespace App.Reports;

public class ReportGenerator
{
    /// <summary>
    /// Generates a PDF report for the given date range.
    /// </summary>
    /// <param name="startDate">Inclusive start of the reporting period.</param>
    /// <param name="endDate">Inclusive end of the reporting period.</param>
    /// <returns>A byte array containing the PDF document.</returns>
    public byte[] GenerateReport(DateTime startDate, DateTime endDate)
    {
        var data = _dataSource.Query(startDate, endDate);
        return _renderer.RenderPdf(data);
    }
}
