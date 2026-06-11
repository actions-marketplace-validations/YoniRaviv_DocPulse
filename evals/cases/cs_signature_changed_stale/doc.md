# ReportGenerator

## GenerateReport

```csharp
public byte[] GenerateReport(DateTime startDate, DateTime endDate)
```

Produces a **PDF** report covering the inclusive date range `[startDate, endDate]`.
Returns the raw PDF bytes, ready to stream to the client.

```csharp
byte[] pdf = generator.GenerateReport(
    new DateTime(2024, 1, 1),
    new DateTime(2024, 3, 31));
```
