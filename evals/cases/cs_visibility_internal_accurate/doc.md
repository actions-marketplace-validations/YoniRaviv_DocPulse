# OrderRepository

## GetByCustomer

```csharp
public IReadOnlyList<Order> GetByCustomer(int customerId)
```

Returns all orders belonging to the specified customer. The list is
read-only; use the write methods to create or cancel orders.
