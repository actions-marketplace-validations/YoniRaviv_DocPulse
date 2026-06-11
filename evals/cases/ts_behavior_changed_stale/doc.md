# formatPrice

`formatPrice(amount)` converts a numeric amount to a display string.

It **rounds to the nearest whole dollar** and prepends `$`:

```
formatPrice(9.7)  // "$10"
formatPrice(4.3)  // "$4"
```
