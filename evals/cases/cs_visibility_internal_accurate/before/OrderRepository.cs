namespace App.Data;

public class OrderRepository
{
    private int _cacheHits = 0;

    /// <summary>Retrieves all orders for the given customer.</summary>
    public IReadOnlyList<Order> GetByCustomer(int customerId)
    {
        return _db.Orders.Where(o => o.CustomerId == customerId).ToList();
    }
}
