# Owner Role + Activity Audit

## Owner Role

Added a new `owner` role.

Owner can:
- Access everything employees/admins can access.
- Open the Owner control room at `/owner/`.
- View all users.
- View all clients.
- View all OPS users.
- View internal CRM.
- View client workspaces.
- View activity logs.

## Creating Owner Accounts

There is no public Owner signup.

Create Owner accounts only through:

`/admin/accounts/user/add/`

Then set:

- `role = owner`
- `is_staff = true` if they should access Django Admin
- `is_superuser = true` only for the main founder/root account

## Activity Logging

The system now logs:

- Authenticated page visits/actions
- Create/update/delete actions on key models
- Actor username and role
- Path, method, status code
- IP address
- User agent
- Model/object affected

Main views:

- `/owner/`
- `/owner/activity/`
- `/owner/users/`
- `/owner/clients/`

## Stable Dependency Policy

Django is now pinned to the stable LTS track:

`Django>=5.2.15,<5.3`

Django 5.2 LTS supports Python 3.14 and receives extended support until April 2028. That is safer for this app than jumping to Django 6.0 immediately.
