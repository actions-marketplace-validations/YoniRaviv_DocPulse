# connect

`connect(host, timeout=30)` opens a TCP connection to `host`.

The `timeout` parameter sets the socket timeout in seconds; it defaults to **30**.
If the server does not respond within that window the call raises `TimeoutError`.
