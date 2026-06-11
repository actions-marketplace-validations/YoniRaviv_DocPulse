# isValidEmail

`isValidEmail(email: string): boolean`

Returns `true` when the email string has a valid format (`local@domain.tld`).
This is a **syntax-only** check — it does not perform DNS lookups or verify
that the mailbox exists.
