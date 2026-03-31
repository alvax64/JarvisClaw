import makeWASocket, { useMultiFileAuthState, DisconnectReason } from '@whiskeysockets/baileys';
import pino from 'pino';
import qrcode from 'qrcode-terminal';
import { createServer } from 'http';
import { readFileSync, writeFileSync, existsSync } from 'fs';

let retryCount = 0;
const MAX_RETRIES = 5;
const HTTP_PORT = 3001;
const CONTACTS_FILE = './contacts_cache.json';
const GROUPS_FILE = './groups_cache.json';
const ALIASES_FILE = './aliases.json';

let activeSock = null;
let contactStore = {};  // name -> jid
let groupStore = {};    // name -> jid (groups)
let aliases = {};       // user-defined aliases

// ── Persistence ──────────────────────────────────────────────────

function loadFromDisk() {
    try {
        if (existsSync(CONTACTS_FILE))
            contactStore = JSON.parse(readFileSync(CONTACTS_FILE, 'utf8'));
    } catch { /* ignore */ }
    try {
        if (existsSync(GROUPS_FILE))
            groupStore = JSON.parse(readFileSync(GROUPS_FILE, 'utf8'));
    } catch { /* ignore */ }
    try {
        if (existsSync(ALIASES_FILE))
            aliases = JSON.parse(readFileSync(ALIASES_FILE, 'utf8'));
    } catch { /* ignore */ }
    console.log(`Cache: ${Object.keys(contactStore).length} contactos, ${Object.keys(groupStore).length} grupos, ${Object.keys(aliases).length} aliases`);
}

function saveContacts() {
    try { writeFileSync(CONTACTS_FILE, JSON.stringify(contactStore, null, 2)); } catch {}
}
function saveGroups() {
    try { writeFileSync(GROUPS_FILE, JSON.stringify(groupStore, null, 2)); } catch {}
}
function saveAliases() {
    try { writeFileSync(ALIASES_FILE, JSON.stringify(aliases, null, 2)); } catch {}
}

// ── Contact/Group helpers ────────────────────────────────────────

function normalize(str) {
    return str.toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '');
}

function addContact(name, jid) {
    if (!name || !jid) return;
    const lower = name.toLowerCase();
    contactStore[lower] = jid;
    const clean = normalize(name);
    if (clean !== lower) contactStore[clean] = jid;
}

function addGroup(name, jid) {
    if (!name || !jid) return;
    const lower = name.toLowerCase();
    groupStore[lower] = jid;
    const clean = normalize(name);
    if (clean !== lower) groupStore[clean] = jid;
}

function searchAll(query) {
    const q = normalize(query);

    // 1. Exact alias match
    for (const [alias, jid] of Object.entries(aliases)) {
        if (normalize(alias) === q) return { name: alias, jid, type: 'alias' };
    }

    // 2. Exact contact match
    if (contactStore[q]) return { name: q, jid: contactStore[q], type: 'contact' };

    // 3. Exact group match
    if (groupStore[q]) return { name: q, jid: groupStore[q], type: 'group' };

    // 4. Fuzzy: name contains query
    for (const [name, jid] of Object.entries(aliases)) {
        if (normalize(name).includes(q)) return { name, jid, type: 'alias' };
    }
    for (const [name, jid] of Object.entries(groupStore)) {
        if (name.includes(q)) return { name, jid, type: 'group' };
    }
    for (const [name, jid] of Object.entries(contactStore)) {
        if (name.includes(q)) return { name, jid, type: 'contact' };
    }

    // 5. Fuzzy: query contains name
    for (const [name, jid] of Object.entries(groupStore)) {
        if (name.length > 2 && q.includes(name)) return { name, jid, type: 'group' };
    }
    for (const [name, jid] of Object.entries(contactStore)) {
        if (name.length > 2 && q.includes(name)) return { name, jid, type: 'contact' };
    }

    return null;
}

function searchAllMultiple(query) {
    const q = normalize(query);
    const results = [];

    for (const [name, jid] of Object.entries(aliases)) {
        if (normalize(name).includes(q)) results.push({ name: `[alias] ${name}`, jid, type: 'alias' });
    }
    for (const [name, jid] of Object.entries(groupStore)) {
        if (name.includes(q)) results.push({ name: `[grupo] ${name}`, jid, type: 'group' });
    }
    for (const [name, jid] of Object.entries(contactStore)) {
        if (name.includes(q)) results.push({ name, jid, type: 'contact' });
    }
    return results;
}

loadFromDisk();

// ── Baileys connection ───────────────────────────────────────────

async function fetchGroups(sock) {
    try {
        const groups = await sock.groupFetchAllParticipating();
        let count = 0;
        for (const [jid, meta] of Object.entries(groups)) {
            if (meta.subject) {
                addGroup(meta.subject, jid);
                count++;
            }
        }
        saveGroups();
        console.log(`Grupos cargados: ${count}`);
    } catch (e) {
        console.error('Error cargando grupos:', e.message);
    }
}

async function startBot() {
    const { state, saveCreds } = await useMultiFileAuthState('./auth_info');

    const sock = makeWASocket.default
        ? makeWASocket.default({
            auth: state,
            logger: pino({ level: 'silent' }),
            printQRInTerminal: false,
            browser: ['Jarvis', 'Chrome', '22.0'],
        })
        : makeWASocket({
            auth: state,
            logger: pino({ level: 'silent' }),
            printQRInTerminal: false,
            browser: ['Jarvis', 'Chrome', '22.0'],
        });

    sock.ev.on('creds.update', saveCreds);

    sock.ev.on('connection.update', async (update) => {
        const { connection, lastDisconnect, qr } = update;

        if (qr) {
            console.log('\n📱 Escanea este QR con WhatsApp:\n');
            qrcode.generate(qr, { small: true });
        }

        if (connection === 'close') {
            activeSock = null;
            const statusCode = lastDisconnect?.error?.output?.statusCode;
            const shouldReconnect = statusCode !== DisconnectReason.loggedOut;

            if (shouldReconnect && retryCount < MAX_RETRIES) {
                retryCount++;
                const delay = Math.min(retryCount * 2000, 10000);
                console.log(`Reconectando en ${delay / 1000}s... (intento ${retryCount}/${MAX_RETRIES})`);
                setTimeout(startBot, delay);
            } else if (!shouldReconnect) {
                console.log('Sesión cerrada por WhatsApp. Borra auth_info/ y vuelve a escanear.');
                process.exit(1);
            } else {
                console.log('Demasiados intentos de reconexión.');
                process.exit(1);
            }
        } else if (connection === 'open') {
            retryCount = 0;
            activeSock = sock;
            console.log('✅ Conectado a WhatsApp!');

            // Fetch all groups on connect
            await fetchGroups(sock);

            console.log(`Total: ${Object.keys(contactStore).length} contactos, ${Object.keys(groupStore).length} grupos`);
            console.log('Escuchando mensajes...\n');
        }
    });

    // Capture contacts
    sock.ev.on('contacts.upsert', (contacts) => {
        for (const c of contacts) addContact(c.name || c.notify, c.id);
        saveContacts();
    });
    sock.ev.on('contacts.update', (updates) => {
        for (const u of updates) addContact(u.name || u.notify, u.id);
        saveContacts();
    });

    // Capture groups updates
    sock.ev.on('groups.upsert', (groups) => {
        for (const g of groups) addGroup(g.subject, g.id);
        saveGroups();
    });
    sock.ev.on('groups.update', (updates) => {
        for (const u of updates) {
            if (u.subject && u.id) addGroup(u.subject, u.id);
        }
        saveGroups();
    });

    // Capture names from incoming messages
    sock.ev.on('messages.upsert', async ({ messages, type }) => {
        let dirty = false;
        for (const msg of messages) {
            if (msg.pushName && msg.key.remoteJid) {
                // If it's a group message, store the group JID too
                if (msg.key.remoteJid.endsWith('@g.us')) {
                    // pushName is the sender, not the group — don't overwrite
                } else {
                    addContact(msg.pushName, msg.key.remoteJid);
                    dirty = true;
                }
            }
        }
        if (dirty) saveContacts();
    });

    // Log incoming messages
    sock.ev.on('messages.upsert', async ({ messages, type }) => {
        if (type !== 'notify') return;
        for (const msg of messages) {
            if (msg.key.fromMe) continue;
            const from = msg.key.remoteJid;
            const text = msg.message?.conversation
                || msg.message?.extendedTextMessage?.text
                || '';
            const pushName = msg.pushName || 'Desconocido';
            console.log(`[${pushName} - ${from}]: ${text}`);
        }
    });

    return sock;
}

// ── HTTP API ─────────────────────────────────────────────────────

function readBody(req) {
    return new Promise((resolve, reject) => {
        let data = '';
        req.on('data', c => data += c);
        req.on('end', () => {
            try { resolve(JSON.parse(data)); }
            catch { reject(new Error('Invalid JSON')); }
        });
        req.on('error', reject);
    });
}

function jsonResponse(res, status, body) {
    res.writeHead(status, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify(body));
}

const server = createServer(async (req, res) => {
    try {
        // POST /send — by phone number or JID
        if (req.method === 'POST' && req.url === '/send') {
            if (!activeSock) return jsonResponse(res, 503, { ok: false, error: 'WhatsApp not connected' });

            const body = await readBody(req);
            let { to, text } = body;
            if (!to || !text) return jsonResponse(res, 400, { ok: false, error: 'Missing "to" or "text"' });

            if (!to.includes('@')) to = to.replace(/[^0-9]/g, '') + '@s.whatsapp.net';

            await activeSock.sendMessage(to, { text });
            console.log(`[SENT → ${to}]: ${text}`);
            return jsonResponse(res, 200, { ok: true, to, text });
        }

        // POST /send-to — by name (searches contacts, groups, aliases)
        if (req.method === 'POST' && req.url === '/send-to') {
            if (!activeSock) return jsonResponse(res, 503, { ok: false, error: 'WhatsApp not connected' });

            const body = await readBody(req);
            const { name, text } = body;
            if (!name || !text) return jsonResponse(res, 400, { ok: false, error: 'Missing "name" or "text"' });

            const match = searchAll(name);
            if (!match) {
                const suggestions = searchAllMultiple(name.length > 3 ? name.substring(0, 3) : name);
                return jsonResponse(res, 404, {
                    ok: false,
                    error: `No contact or group found matching "${name}"`,
                    suggestions: suggestions.slice(0, 10),
                });
            }

            await activeSock.sendMessage(match.jid, { text });
            console.log(`[SENT → ${match.type}:${match.name} (${match.jid})]: ${text}`);
            return jsonResponse(res, 200, { ok: true, contact: match.name, type: match.type, to: match.jid, text });
        }

        // GET /contacts?q= — search contacts AND groups
        if (req.method === 'GET' && req.url.startsWith('/contacts')) {
            const url = new URL(req.url, 'http://localhost');
            const query = url.searchParams.get('q') || '';

            if (!query) {
                return jsonResponse(res, 200, {
                    ok: true,
                    contacts: Object.keys(contactStore).length,
                    groups: Object.keys(groupStore).length,
                    aliases: Object.keys(aliases).length,
                    all_contacts: contactStore,
                    all_groups: groupStore,
                    all_aliases: aliases,
                });
            }

            const results = searchAllMultiple(query);
            return jsonResponse(res, 200, { ok: true, query, matches: results });
        }

        // GET /groups — list all groups
        if (req.method === 'GET' && req.url === '/groups') {
            return jsonResponse(res, 200, { ok: true, groups: groupStore });
        }

        // POST /alias
        if (req.method === 'POST' && req.url === '/alias') {
            const body = await readBody(req);
            const { alias, phone, name: contactName } = body;
            if (!alias) return jsonResponse(res, 400, { ok: false, error: 'Missing "alias"' });

            if (phone) {
                const jid = phone.replace(/[^0-9]/g, '') + '@s.whatsapp.net';
                aliases[alias.toLowerCase()] = jid;
                saveAliases();
                return jsonResponse(res, 200, { ok: true, alias, jid });
            }
            if (contactName) {
                const match = searchAll(contactName);
                if (!match) return jsonResponse(res, 404, { ok: false, error: `"${contactName}" not found` });
                aliases[alias.toLowerCase()] = match.jid;
                saveAliases();
                return jsonResponse(res, 200, { ok: true, alias, jid: match.jid, resolved_from: match.name });
            }
            return jsonResponse(res, 400, { ok: false, error: 'Need "phone" or "name"' });
        }

        // POST /refresh-groups — force re-fetch groups
        if (req.method === 'POST' && req.url === '/refresh-groups') {
            if (!activeSock) return jsonResponse(res, 503, { ok: false, error: 'WhatsApp not connected' });
            await fetchGroups(activeSock);
            return jsonResponse(res, 200, { ok: true, groups: Object.keys(groupStore).length });
        }

        // GET /status
        if (req.method === 'GET' && req.url === '/status') {
            return jsonResponse(res, 200, {
                ok: true,
                connected: activeSock !== null,
                contacts: Object.keys(contactStore).length,
                groups: Object.keys(groupStore).length,
                aliases: Object.keys(aliases).length,
            });
        }

        jsonResponse(res, 404, { error: 'POST /send, /send-to, /alias, /refresh-groups | GET /contacts?q=, /groups, /status' });

    } catch (err) {
        console.error('HTTP error:', err.message);
        jsonResponse(res, 500, { ok: false, error: err.message });
    }
});

server.listen(HTTP_PORT, '127.0.0.1', () => {
    console.log(`WhatsApp API listening on http://127.0.0.1:${HTTP_PORT}`);
});

startBot().catch((err) => {
    console.error('Error fatal:', err.message);
    process.exit(1);
});
