# Microsoft Exchange Setup Guide

Koda2 supports both **on-premises Exchange servers** and **Office 365**.

## Quick Comparison

| Feature | Exchange On-Premises (EWS) | Office 365 (MS Graph) |
|---------|---------------------------|----------------------|
| Server URL | Your company's server | https://graph.microsoft.com |
| Username | Often DOMAIN\\user | user@domain.com |
| Auth Method | Basic auth | OAuth 2.0 |
| Requirements | Exchange 2013+ | Microsoft 365 subscription |

## Option 1: On-Premises Exchange (EWS)

Use this if your company runs its own Exchange server.

### Required Information

Ask your IT department for:

1. **EWS Server URL** 
   - Format: `https://mail.company.com/EWS/Exchange.asmx`
   - Sometimes: `https://exchange.company.com/ews/exchange.asmx`

2. **Username**
   - Can be different from email!
   - Common formats:
     - `DOMAIN\username` (e.g., `COMPANY\john.doe`)
     - `username` (without domain)
     - `username@company.local` (internal domain)

3. **Password**
   - Your domain/Active Directory password

4. **Email Address**
   - Your actual email address (e.g., `john.doe@company.com`)

### Configuration Example

```env
EWS_SERVER=https://mail.company.com/EWS/Exchange.asmx
EWS_USERNAME=COMPANY\john.doe
EWS_PASSWORD=your_domain_password
EWS_EMAIL=john.doe@company.com
```

**Note**: `EWS_USERNAME` and `EWS_EMAIL` are often DIFFERENT!

### Finding Your EWS URL

Ask your IT admin, or try these common patterns:
- `https://mail.company.com/EWS/Exchange.asmx`
- `https://exchange.company.com/ews/exchange.asmx`
- `https://autodiscover.company.com/autodiscover/autodiscover.xml`

### Testing the Connection

After configuring, run:
```bash
koda2 --test-exchange
```

## Option 2: Office 365 / Microsoft 365

Use this for Microsoft's cloud service.

### Required Information

1. **Client ID** (Application ID)
2. **Client Secret**
3. **Tenant ID**

### Setup Steps

1. Go to [Azure Portal](https://portal.azure.com/)
2. Navigate to "Azure Active Directory" → "App registrations"
3. Click "New registration"
4. Name: "Koda2 Assistant"
5. Supported account types: "Accounts in this organizational directory only"
6. Click "Register"
7. Copy the **Application (client) ID**
8. Copy the **Directory (tenant) ID**
9. Go to "Certificates & secrets" → "New client secret"
10. Add a description and expiration
11. Copy the secret **VALUE** (you won't see it again!)
12. Go to "API permissions" → "Add permission"
13. Add these Microsoft Graph permissions:
    - `Calendars.ReadWrite`
    - `Mail.ReadWrite`
    - `User.Read`
14. Click "Grant admin consent" (or ask your admin to do this)

### Configuration Example

```env
MSGRAPH_CLIENT_ID=12345678-1234-1234-1234-123456789012
MSGRAPH_CLIENT_SECRET=your_secret_here
MSGRAPH_TENANT_ID=87654321-4321-4321-4321-210987654321
```

## Common Issues

### "401 Unauthorized" (Exchange)
- Check username format (try with and without DOMAIN\\)
- Verify password hasn't expired
- Ask IT if EWS is enabled for your account

### "Autodiscover failed"
- Use explicit EWS_SERVER URL instead of autodiscover
- Check if the URL is accessible from your network

### "Access denied" (Office 365)
- Admin needs to grant consent for the application
- Check that you added the correct API permissions

### Two-Factor Authentication (2FA)
**Exchange EWS**: Use app-specific password if 2FA is enabled
**Office 365**: OAuth handles 2FA automatically via browser

## Security Notes

- Passwords are stored encrypted in `.env` file
- For Exchange, consider using app-specific passwords
- Office 365 OAuth is more secure than basic auth
- Never share your `.env` file
