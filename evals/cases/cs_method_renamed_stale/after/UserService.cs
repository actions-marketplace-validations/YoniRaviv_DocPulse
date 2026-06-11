namespace App.Services;

public class UserService
{
    /// <summary>
    /// Looks up a user by their unique identifier.
    /// </summary>
    /// <param name="id">The user's primary key.</param>
    /// <returns>The matching <see cref="User"/>, or <c>null</c> if not found.</returns>
    public User? FindById(int id)
    {
        return _repository.Find(id);
    }
}
