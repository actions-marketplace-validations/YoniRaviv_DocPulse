# UserService

## GetUserById

```csharp
public User? GetUserById(int id)
```

Returns the `User` with the given primary key, or `null` if no such user exists.

```csharp
var user = userService.GetUserById(42);
if (user is null) return NotFound();
```
