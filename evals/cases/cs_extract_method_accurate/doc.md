# InvoiceService

## CalculateTotal

```csharp
public decimal CalculateTotal(IEnumerable<LineItem> items, decimal taxRate)
```

Returns the total amount due: the sum of `(UnitPrice × Quantity)` for all line
items, plus the given `taxRate` fraction applied to that subtotal.

```csharp
decimal total = invoiceService.CalculateTotal(order.Items, taxRate: 0.08m);
```
