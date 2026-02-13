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
const fs = require('fs');
const { execSync } = require('child_process');

const PORT = parseInt(process.env.WHATSAPP_BRIDGE_PORT || '3001', 10);
const CALLBACK_URL = process.env.KODA2_CALLBACK_URL || 'http://localhost:8000/api/whatsapp/webhook';
const AUTH_DIR = process.env.WHATSAPP_AUTH_DIR || path.join(__dirname, '..', '..', '..', '..', 'data', 'whatsapp_session');
const MAX_INIT_RETRIES = 3;
const INIT_RETRY_DELAY_MS = 3000;

const app = express();
app.use(express.json());

let currentQR = null;
let clientReady = false;
let clientInfo = null;
let initError = null;
let disconnectReason = null;
let messageQueue = [];
const MAX_QUEUE = 200;

// Flag to prevent reply loops: true while the bot is sending a message via /send
let isSendingReply = false;

/**
 * Kill any stale Chrome/Chromium processes that hold the session lock.
 * This prevents "The browser is already running" errors on restart.
 */
function killStaleChromeProcesses() {
    const sessionDir = path.join(AUTH_DIR, 'session');
    const lockFile = path.join(sessionDir, 'SingletonLock');

    // Remove lock files if they exist
    for (const f of ['SingletonLock', 'SingletonSocket', 'SingletonCookie']) {
        const p = path.join(sessionDir, f);
        try { fs.unlinkSync(p); console.log(`[Bridge] Removed stale lock: ${f}`); } catch(e) { /* ignore */ }
    }

    // Kill any orphaned chrome processes using this data dir
    try {
        if (process.platform !== 'win32') {
            execSync(`pkill -f "user-data-dir=.*whatsapp_session" 2>/dev/null || true`, { timeout: 5000 });
        }
    } catch(e) { /* ignore */ }
}

function createClient() {
    return new Client({
        authStrategy: new LocalAuth({ dataPath: AUTH_DIR }),
        puppeteer: {
            headless: true,
            args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage'],
        },
    });
}

let client = createClient();

// ── Message handlers (named so they can be re-attached on reconnect) ──

async function onMessageCreate(msg) {
    const isFromMe = msg.fromMe;
    const chat = await msg.getChat();

    // Detect self-message: the "Message yourself" chat has your own number as
    // the chat ID. We must check that the RECIPIENT (chat/to) is ourselves,
    // not just that the sender is ourselves (fromMe covers that).
    // IMPORTANT: Do NOT check msg.from === myWid here — for ALL outgoing
    // messages msg.from is your own WID, which would make every outgoing
    // message look like a self-message.
    const myWid = clientInfo ? clientInfo.wid._serialized : null;
    const chatIdStr = chat.id ? chat.id._serialized : null;
    const isToSelf = isFromMe && (
        (myWid && chatIdStr && chatIdStr === myWid) ||
        (myWid && msg.to === myWid) ||
        msg.to === msg.from
    );

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
        mimetype: msg.mimetype || null,
        filename: msg.filename || null,
        myWid: myWid,
        chatId: chat.id ? chat.id._serialized : null,
    };

    // Log ALL messages for debugging (including self-messages)
    console.log(`[WhatsApp] msg from=${parsed.from} to=${parsed.to} myWid=${myWid} chatId=${parsed.chatId} fromMe=${isFromMe} isToSelf=${isToSelf}: ${(parsed.body || '').substring(0, 100)}`);

    // Queue for polling
    messageQueue.push(parsed);
    if (messageQueue.length > MAX_QUEUE) {
        messageQueue = messageQueue.slice(-MAX_QUEUE);
    }

    // Forward to Koda2 callback if it's a self-message (user messaging themselves)
    // Skip messages sent by the bot itself to prevent infinite reply loops.
    // isSendingReply is true while /send is executing client.sendMessage(),
    // which triggers message_create synchronously before the send resolves.
    if (isFromMe && !isToSelf) {
        console.log(`[WhatsApp] Outgoing to other contact (ignored): ${(parsed.body || '').substring(0, 50)}`);
    } else if (isFromMe && isToSelf && isSendingReply) {
        console.log(`[WhatsApp] Skipping bot's own reply (loop prevention): ${(parsed.body || '').substring(0, 50)}`);
    } else if (isFromMe && isToSelf) {
        console.log(`[WhatsApp] Forwarding self-message to Koda2: ${(parsed.body || '').substring(0, 50)}...`);
        try {
            const resp = await fetch(CALLBACK_URL, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(parsed),
            });
            if (!resp.ok) {
                console.warn('[WhatsApp] Callback failed:', resp.status);
            } else {
                console.log('[WhatsApp] Callback successful');
            }
        } catch (err) {
            console.warn('[WhatsApp] Callback error (Koda2 might not be running):', err.message);
        }
    }
}

async function onMessage(msg) {
    // Only process messages from others here (self-messages handled by onMessageCreate)
    if (msg.fromMe) return;
    
    const chat = await msg.getChat();
    const parsed = {
        id: msg.id._serialized,
        from: msg.from,
        to: msg.to,
        fromMe: false,
        isToSelf: false,
        isGroup: chat.isGroup,
        body: msg.body,
        type: msg.type,
        timestamp: msg.timestamp,
        chatName: chat.name || msg.from,
        hasMedia: msg.hasMedia,
        mimetype: msg.mimetype || null,
        filename: msg.filename || null,
        myWid: clientInfo ? clientInfo.wid : null,
        chatId: chat.id ? chat.id._serialized : null,
    };

    // Log incoming messages from others
    console.log(`[WhatsApp] Incoming from ${parsed.from}: ${(parsed.body || '').substring(0, 100)}`);

    // Queue for polling
    messageQueue.push(parsed);
    if (messageQueue.length > MAX_QUEUE) {
        messageQueue = messageQueue.slice(-MAX_QUEUE);
    }
}

// ── HTTP API ────────────────────────────────────────────────────────

app.get('/status', (req, res) => {
    res.json({
        ready: clientReady,
        qr_available: currentQR !== null,
        info: clientInfo,
        error: initError,
        disconnected: disconnectReason,
        needs_qr: !clientReady && !clientInfo && !initError,
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
            isSendingReply = true;
            const sent = await client.sendMessage(chatId, media, { caption: media_caption || message || '' });
            isSendingReply = false;
            return res.json({ status: 'sent', id: sent.id._serialized });
        }

        isSendingReply = true;
        const sent = await client.sendMessage(chatId, message);
        isSendingReply = false;
        console.log(`[WhatsApp] Sent bot reply (id=${sent.id._serialized})`);
        res.json({ status: 'sent', id: sent.id._serialized });
    } catch (err) {
        isSendingReply = false;
        console.error('Send error:', err.message);
        res.status(500).json({ error: err.message });
    }
});

app.post('/send-media', async (req, res) => {
    if (!clientReady) {
        return res.status(503).json({ error: 'WhatsApp not connected' });
    }
    const { to, file_path, base64_data, mimetype, filename, caption } = req.body;
    if (!to || (!file_path && !base64_data)) {
        return res.status(400).json({ error: 'Missing "to" and "file_path" or "base64_data"' });
    }

    try {
        // Normalize phone number to WhatsApp ID format
        const chatId = to.includes('@') ? to : `${to.replace(/[^0-9]/g, '')}@c.us`;
        
        const { MessageMedia } = require('whatsapp-web.js');
        let media;
        
        if (file_path) {
            // Read file from disk
            const fs = require('fs');
            const path = require('path');
            const fullPath = path.resolve(file_path);
            
            if (!fs.existsSync(fullPath)) {
                return res.status(400).json({ error: `File not found: ${file_path}` });
            }
            
            const fileData = fs.readFileSync(fullPath, { encoding: 'base64' });
            const mimeType = mimetype || 'application/octet-stream';
            const fileName = filename || path.basename(fullPath);
            
            media = new MessageMedia(mimeType, fileData, fileName);
        } else if (base64_data) {
            // Use provided base64 data
            media = new MessageMedia(mimetype || 'application/octet-stream', base64_data, filename || 'file');
        }
        
        isSendingReply = true;
        const sent = await client.sendMessage(chatId, media, { caption: caption || '' });
        isSendingReply = false;
        
        console.log(`[WhatsApp] Sent media (id=${sent.id._serialized})`);
        res.json({ status: 'sent', id: sent.id._serialized, filename: filename || file_path });
    } catch (err) {
        isSendingReply = false;
        console.error('Send media error:', err.message);
        res.status(500).json({ error: err.message });
    }
});

app.post('/typing', async (req, res) => {
    if (!clientReady) {
        return res.status(503).json({ error: 'WhatsApp not connected' });
    }
    const { to } = req.body;
    if (!to) {
        return res.status(400).json({ error: 'Missing "to"' });
    }
    try {
        const chatId = to.includes('@') ? to : `${to.replace(/[^0-9]/g, '')}@c.us`;
        const chat = await client.getChatById(chatId);
        await chat.sendStateTyping();
        res.json({ status: 'typing' });
    } catch (err) {
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

// ── Media Download ──────────────────────────────────────────────────

app.post('/download', async (req, res) => {
    if (!clientReady) {
        return res.status(503).json({ error: 'WhatsApp not connected' });
    }
    
    const { message_id, media_url, filename } = req.body;
    
    console.log('[WhatsApp] Download request:', { message_id: message_id?.substring(0, 20), media_url: media_url?.substring(0, 50) });
    
    try {
        // If message_id is provided, fetch media from that message
        if (message_id) {
            console.log('[WhatsApp] Fetching message by ID:', message_id.substring(0, 30));
            
            let msg;
            try {
                msg = await client.getMessageById(message_id);
            } catch (err) {
                console.error('[WhatsApp] Failed to get message:', err.message);
                return res.status(404).json({ error: 'Message not found or expired: ' + err.message });
            }
            
            if (!msg) {
                return res.status(404).json({ error: 'Message not found' });
            }
            
            console.log('[WhatsApp] Message found, hasMedia:', msg.hasMedia);
            
            if (!msg.hasMedia) {
                return res.status(400).json({ error: 'Message has no media' });
            }
            
            console.log('[WhatsApp] Downloading media...');
            const media = await msg.downloadMedia();
            if (!media) {
                return res.status(500).json({ error: 'Failed to download media from WhatsApp' });
            }
            
            console.log('[WhatsApp] Media downloaded, mimetype:', media.mimetype);
            
            // Generate filename if not provided
            let ext = '';
            if (media.mimetype) {
                const mimeToExt = {
                    'image/jpeg': '.jpg',
                    'image/png': '.png',
                    'image/gif': '.gif',
                    'image/webp': '.webp',
                    'video/mp4': '.mp4',
                    'video/ogg': '.ogv',
                    'audio/ogg': '.ogg',
                    'audio/mpeg': '.mp3',
                    'audio/mp4': '.m4a',
                    'application/pdf': '.pdf',
                };
                ext = mimeToExt[media.mimetype] || '.bin';
            }
            const finalFilename = filename || `media_${Date.now()}${ext}`;
            
            // Save to downloads directory
            const downloadDir = path.join(__dirname, '..', '..', '..', '..', 'data', 'whatsapp_downloads');
            fs.mkdirSync(downloadDir, { recursive: true });
            const filePath = path.join(downloadDir, finalFilename);
            fs.writeFileSync(filePath, media.data, 'base64');
            
            console.log(`[WhatsApp] Media downloaded: ${filePath}`);
            return res.json({
                success: true,
                filename: finalFilename,
                path: filePath,
                mimetype: media.mimetype,
                size: media.data.length,
            });
        }
        
        // If media_url is provided (for external URLs)
        if (media_url) {
            const { MessageMedia } = require('whatsapp-web.js');
            const media = await MessageMedia.fromUrl(media_url);
            
            let ext = '';
            if (media.mimetype) {
                const mimeToExt = {
                    'image/jpeg': '.jpg', 'image/png': '.png', 'image/gif': '.gif',
                    'image/webp': '.webp', 'video/mp4': '.mp4', 'application/pdf': '.pdf',
                };
                ext = mimeToExt[media.mimetype] || '.bin';
            }
            const finalFilename = filename || `download_${Date.now()}${ext}`;
            
            const downloadDir = path.join(__dirname, '..', '..', '..', '..', 'data', 'whatsapp_downloads');
            fs.mkdirSync(downloadDir, { recursive: true });
            const filePath = path.join(downloadDir, finalFilename);
            fs.writeFileSync(filePath, media.data, 'base64');
            
            return res.json({
                success: true,
                filename: finalFilename,
                path: filePath,
                mimetype: media.mimetype,
            });
        }
        
        res.status(400).json({ error: 'Missing message_id or media_url' });
    } catch (err) {
        console.error('[WhatsApp] Download error:', err.message);
        res.status(500).json({ error: err.message });
    }
});

// Enhanced webhook with media info
app.get('/media-info/:messageId', async (req, res) => {
    if (!clientReady) {
        return res.status(503).json({ error: 'WhatsApp not connected' });
    }
    
    try {
        const msg = await client.getMessageById(req.params.messageId);
        if (!msg.hasMedia) {
            return res.json({ hasMedia: false });
        }
        
        res.json({
            hasMedia: true,
            type: msg.type,
            mimetype: msg.mimetype,
            filename: msg.filename || null,
            body: msg.body,  // caption
        });
    } catch (err) {
        res.status(500).json({ error: err.message });
    }
});

// ── Initialization with retry ────────────────────────────────────────

function setupClientEvents(c) {
    c.on('qr', (qr) => {
        currentQR = qr;
        initError = null;
        disconnectReason = null;
        console.log('\n╔══════════════════════════════════════════╗');
        console.log('║  Scan this QR code with WhatsApp:        ║');
        console.log('╚══════════════════════════════════════════╝\n');
        qrcode.generate(qr, { small: true });
        console.log('\nOr open http://localhost:' + PORT + '/qr in your browser.\n');
    });
    c.on('ready', () => {
        clientReady = true;
        currentQR = null;
        initError = null;
        disconnectReason = null;
        clientInfo = {
            pushname: c.info.pushname,
            wid: c.info.wid._serialized,
            phone: c.info.wid.user,
            platform: c.info.platform,
        };
        console.log(`\n✓ WhatsApp connected as: ${clientInfo.pushname} (${clientInfo.phone})\n`);
    });
    c.on('authenticated', () => {
        console.log('✓ WhatsApp authenticated (session restored)');
        currentQR = null;
        initError = null;
    });
    c.on('auth_failure', (msg) => {
        console.error('✗ WhatsApp auth failed:', msg);
        clientReady = false;
        initError = 'auth_failure: ' + msg;
    });
    c.on('disconnected', (reason) => {
        console.warn('✗ WhatsApp disconnected:', reason);
        clientReady = false;
        clientInfo = null;
        disconnectReason = reason;
        console.log('[Bridge] Will attempt to reinitialize in 5 seconds...');
        setTimeout(() => initializeWithRetry(), 5000);
    });
    c.on('message_create', onMessageCreate);
    c.on('message', onMessage);
}

async function initializeWithRetry() {
    for (let attempt = 1; attempt <= MAX_INIT_RETRIES; attempt++) {
        console.log(`[Bridge] Initialization attempt ${attempt}/${MAX_INIT_RETRIES}...`);
        initError = null;
        disconnectReason = null;

        // Clean up stale locks/processes before each attempt
        killStaleChromeProcesses();

        // Destroy old client if it exists, create fresh one
        try { await client.destroy(); } catch(e) { /* ignore */ }
        client = createClient();
        setupClientEvents(client);

        try {
            await client.initialize();
            console.log('[Bridge] Client initialized successfully');
            return; // success
        } catch(err) {
            console.error(`[Bridge] Init attempt ${attempt} failed:`, err.message);
            initError = err.message;

            if (attempt < MAX_INIT_RETRIES) {
                console.log(`[Bridge] Retrying in ${INIT_RETRY_DELAY_MS/1000}s...`);
                await new Promise(r => setTimeout(r, INIT_RETRY_DELAY_MS));
            }
        }
    }
    console.error(`[Bridge] All ${MAX_INIT_RETRIES} init attempts failed. Bridge HTTP API still running — check /status for details.`);
}

// ── Start ───────────────────────────────────────────────────────────

app.listen(PORT, () => {
    console.log(`Koda2 WhatsApp Bridge listening on http://localhost:${PORT}`);
    console.log('Initializing WhatsApp Web client...\n');
    initializeWithRetry();
});
