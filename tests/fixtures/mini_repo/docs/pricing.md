# Pricing

This document describes the pricing system.

## Price Formatting

The `formatPrice` function converts a price in cents to a human-readable string.
It uses locale-aware formatting and returns a value like `$12.99`.

## Cart

The `Cart.AddItem` method adds a product to the shopping cart by SKU.
It validates inventory levels before adding the item.
