/**
 * Koda2 WhatsApp Web Bridge
 * 
 * Connects to WhatsApp via QR code scan (whatsapp-web.js).
 * Exposes a local HTTP API for the Python backend to:
 *   - Get QR code for pairing
 *   - Send messages to any number
 *   - Receive incoming messages via polling or callback
 * 
 * Messages from the user's own number are forwarded to Koda2 for processing.
 */

const { Client, LocalAuth } = require('whatsapp-web.js');
const qrcode = require('qrcode-terminal');
const express = require('express');
const path = require('path');

const PORT = parseInt(process.env.WHATSAPP_BRIDGE_PORT || '3001', 10);
const CALLBACK_URL = process.env.KODA2_CALLBACK_URL || 'http://localhost:8000/api/whatsapp/webhook';
const AUTH_DIR = process.env.WHATSAPP_AUTH_DIR || path.join(__dirname, '..', '..', '..', '..', 'data', 'whatsapp_session');

const app = express();
app.use(express.json());

let currentQR = null;
let clientReady = false;
let clientInfo = null;
let messageQueue = [];
const MAX_QUEUE = 200;

const client = new Client({
    authStrategy: new LocalAuth({ dataPath: AUTH_DIR }),
    puppeteer: {
        headless: true,
        args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage'],
    },
});

// ── WhatsApp Events ─────────────────────────────────────────────────

client.on('qr', (qr) => {
    currentQR = qr;
    console.log('\n╔══════════════════════════════════════════╗');
    console.log('║  Scan this QR code with WhatsApp:        ║');
    console.log('╚══════════════════════════════════════════╝\n');
    qrcode.generate(qr, { small: true });
    console.log('\nOr open http://localhost:' + PORT + '/qr in your browser.\n');
});

client.on('ready', () => {
    clientReady = true;
    currentQR = null;
    clientInfo = {
        pushname: client.info.pushname,
        wid: client.info.wid._serialized,
        phone: client.info.wid.user,
        platform: client.info.platform,
    };
    console.log(`\n✓ WhatsApp connected as: ${clientInfo.pushname} (${clientInfo.phone})\n`);
});

client.on('authenticated', () => {
    console.log('✓ WhatsApp authenticated (session restored)');
    currentQR = null;
});

client.on('auth_failure', (msg) => {
    console.error('✗ WhatsApp auth failed:', msg);
    clientReady = false;
});

client.on('disconnected', (reason) => {
    console.warn('✗ WhatsApp disconnected:', reason);
    clientReady = false;
    clientInfo = null;
});

client.on('message', async (msg) => {
    const isFromMe = msg.fromMe;
    const isToSelf = msg.to === msg.from;
    const chat = await msg.getChat();

    const parsed = {
        id: msg.id._serialized,
        from: msg.from,
        to: msg.to,
        fromMe: isFromMe,
        isToSelf: isToSelf,
        isGroup: chat.isGroup,
        body: msg.body,
        type: msg.type,
        timestamp: msg.timestamp,
        chatName: chat.name || msg.from,
        hasMedia: msg.hasMedia,
    };

    // Queue for polling
    messageQueue.push(parsed);
    if (messageQueue.length > MAX_QUEUE) {
        messageQueue = messageQueue.slice(-MAX_QUEUE);
    }

    // Forward to Koda2 callback if it's a self-message (user messaging themselves)
    if (isFromMe && isToSelf) {
        try {
            const resp = await fetch(CALLBACK_URL, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(parsed),
            });
            if (!resp.ok) {
                console.warn('Callback failed:', resp.status);
            }
        } catch (err) {
            // Koda2 might not be running yet, that's fine
        }
    }
});

// ── HTTP API ────────────────────────────────────────────────────────

app.get('/status', (req, res) => {
    res.json({
        ready: clientReady,
        qr_available: currentQR !== null,
        info: clientInfo,
    });
});

app.get('/qr', (req, res) => {
    if (clientReady) {
        return res.json({ status: 'already_connected', info: clientInfo });
    }
    if (!currentQR) {
        return res.json({ status: 'waiting_for_qr', message: 'QR not yet generated. Please wait...' });
    }
    // Return QR as text (for terminal display) and as data URL
    res.json({
        status: 'scan_required',
        qr: currentQR,
        qr_url: `https://api.qrserver.com/v1/create-qr-code/?size=300x300&data=${encodeURIComponent(currentQR)}`,
    });
});

app.post('/send', async (req, res) => {
    if (!clientReady) {
        return res.status(503).json({ error: 'WhatsApp not connected' });
    }
    const { to, message, media_url, media_caption } = req.body;
    if (!to || (!message && !media_url)) {
        return res.status(400).json({ error: 'Missing "to" and "message" or "media_url"' });
    }

    try {
        // Normalize phone number to WhatsApp ID format
        const chatId = to.includes('@') ? to : `${to.replace(/[^0-9]/g, '')}@c.us`;

        if (media_url) {
            const { MessageMedia } = require('whatsapp-web.js');
            const media = await MessageMedia.fromUrl(media_url);
            const sent = await client.sendMessage(chatId, media, { caption: media_caption || message || '' });
            return res.json({ status: 'sent', id: sent.id._serialized });
        }

        const sent = await client.sendMessage(chatId, message);
        res.json({ status: 'sent', id: sent.id._serialized });
    } catch (err) {
        console.error('Send error:', err.message);
        res.status(500).json({ error: err.message });
    }
});

app.get('/messages', (req, res) => {
    const since = parseInt(req.query.since || '0', 10);
    const selfOnly = req.query.self_only === 'true';
    let msgs = messageQueue.filter(m => m.timestamp > since);
    if (selfOnly) {
        msgs = msgs.filter(m => m.fromMe && m.isToSelf);
    }
    res.json({ messages: msgs, count: msgs.length });
});

app.get('/contacts', async (req, res) => {
    if (!clientReady) {
        return res.status(503).json({ error: 'WhatsApp not connected' });
    }
    try {
        const contacts = await client.getContacts();
        const list = contacts
            .filter(c => c.isMyContact && !c.isGroup)
            .map(c => ({
                id: c.id._serialized,
                name: c.name || c.pushname || '',
                number: c.number,
                pushname: c.pushname || '',
            }));
        res.json({ contacts: list });
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
});

app.post('/logout', async (req, res) => {
    try {
        await client.logout();
        clientReady = false;
        clientInfo = null;
        res.json({ status: 'logged_out' });
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
});

// ── Start ───────────────────────────────────────────────────────────

app.listen(PORT, () => {
    console.log(`Koda2 WhatsApp Bridge listening on http://localhost:${PORT}`);
    console.log('Initializing WhatsApp Web client...\n');
});

client.initialize();
