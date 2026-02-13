# Koda2 — Tool Usage Guidelines

## Email
- Use `read_email` to fetch from ALL accounts (Google, Exchange, IMAP, Office365)
- Each email has an `account` field showing which account it belongs to
- Use `get_email_detail` to read the full body of a specific email
- Use `reply_email` to reply (supports reply_all)
- Use `search_email` to find emails by keyword across all accounts
- Use `send_email` with `account` param to send from a specific account

## Calendar
- Use `list_events` to check upcoming events
- Use `create_event` to schedule meetings
- Always include timezone info

## Contacts
- Contact names are auto-resolved to phone/email
- Pass names directly to `send_whatsapp` or `send_email`

## Shell
- Full access to terminal commands (ls, cat, find, grep, git, python, etc.)
- No sudo or dangerous system operations

## Memory
- Use `store_memory` to save important facts the user tells you
- Use `search_memory` to recall relevant context
- Categories: preference, fact, note, project, contact, habit

## WhatsApp
- Use `send_whatsapp` for messages
- Use `send_file` with channel="whatsapp" for files

## Browser
- Use `browse_url` to open and read web pages
- Use `browser_action` for interactive web automation
