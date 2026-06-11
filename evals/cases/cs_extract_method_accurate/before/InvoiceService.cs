namespace App.Billing;

public class InvoiceService
{
    /// <summary>
    /// Calculates the total amount due, including applicable taxes.
    /// </summary>
    public decimal CalculateTotal(IEnumerable<LineItem> items, decimal taxRate)
    {
        decimal subtotal = 0m;
        foreach (var item in items)
        {
            subtotal += item.UnitPrice * item.Quantity;
        }
        return subtotal + subtotal * taxRate;
    }
}
