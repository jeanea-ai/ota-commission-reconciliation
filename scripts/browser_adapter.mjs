#!/usr/bin/env node
/* Read-only SkyTouch adapter over Chrome DevTools Protocol. */

import process from "node:process";

const CDP_HTTP = (process.env.OTA_CDP_ENDPOINT || "http://127.0.0.1:18800").replace(/\/$/, "");
const TIMEOUT_MS = Number(process.env.OTA_BROWSER_TIMEOUT_MS || 45000);
const SKYTOUCH_BASE_URL = "https://www.skytouchhos.com/pms/";
const SEARCH_PATH = process.env.OTA_SKYTOUCH_SEARCH_PATH || "FindReservationInitialize.init";
const SKYTOUCH_HOSTS = new Set(["www.skytouchhos.com", "skytouchhos.com"]);

function fail(message) {
  process.stdout.write(JSON.stringify({ ok: false, error: message }));
  process.exitCode = 1;
}

async function readInput() {
  let body = "";
  for await (const chunk of process.stdin) body += chunk;
  if (!body.trim()) throw new Error("adapter request is empty");
  return JSON.parse(body);
}

async function fetchJson(url, options = {}) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);
  try {
    const response = await fetch(url, { ...options, signal: controller.signal });
    if (!response.ok) throw new Error(`CDP endpoint returned HTTP ${response.status}`);
    return await response.json();
  } finally {
    clearTimeout(timer);
  }
}

class CDP {
  constructor(url) {
    this.url = url;
    this.nextId = 1;
    this.pending = new Map();
    this.events = [];
  }

  async open() {
    await new Promise((resolve, reject) => {
      const ws = new WebSocket(this.url);
      const timer = setTimeout(() => reject(new Error("timed out connecting to shared browser")), TIMEOUT_MS);
      ws.addEventListener("open", () => { clearTimeout(timer); this.ws = ws; resolve(); });
      ws.addEventListener("error", () => { clearTimeout(timer); reject(new Error("could not connect to shared browser")); });
      ws.addEventListener("message", event => this.onMessage(event.data));
      ws.addEventListener("close", () => {
        for (const { reject: rejectPending } of this.pending.values()) rejectPending(new Error("shared browser connection closed"));
        this.pending.clear();
      });
    });
    await this.call("Runtime.enable");
    await this.call("Page.enable");
  }

  onMessage(raw) {
    const message = JSON.parse(raw);
    if (message.id && this.pending.has(message.id)) {
      const pending = this.pending.get(message.id);
      this.pending.delete(message.id);
      if (message.error) pending.reject(new Error(message.error.message));
      else pending.resolve(message.result);
    } else if (message.method) {
      this.events.push(message.method);
    }
  }

  call(method, params = {}) {
    const id = this.nextId++;
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id);
        reject(new Error(`${method} timed out`));
      }, TIMEOUT_MS);
      this.pending.set(id, {
        resolve: value => { clearTimeout(timer); resolve(value); },
        reject: error => { clearTimeout(timer); reject(error); },
      });
      this.ws.send(JSON.stringify({ id, method, params }));
    });
  }

  async evaluate(expression) {
    const result = await this.call("Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true });
    if (result.exceptionDetails) throw new Error("browser page script failed");
    return result.result?.value;
  }

  async ready() {
    const deadline = Date.now() + TIMEOUT_MS;
    while (Date.now() < deadline) {
      try {
        if (await this.evaluate("document.readyState === 'complete'")) return;
      } catch {}
      await new Promise(resolve => setTimeout(resolve, 150));
    }
    throw new Error("PMS page did not finish loading");
  }

  async goto(url) {
    this.events.length = 0;
    await this.call("Page.navigate", { url });
    await this.ready();
  }

  close() { if (this.ws) this.ws.close(); }
}

function pageScript(fn, argument) {
  return `(${fn.toString()})(${JSON.stringify(argument)})`;
}

function joinUrl(base, path) {
  const normalized = base.endsWith("/") ? base : `${base}/`;
  return new URL(path, normalized).href;
}

function assertSameOrigin(url, base) {
  if (new URL(url).origin !== new URL(base).origin) throw new Error("PMS page attempted cross-origin navigation");
  return url;
}

async function connectPage(targetId) {
  const targets = await fetchJson(`${CDP_HTTP}/json`);
  const pages = targets.filter(target => target.type === "page" && target.webSocketDebuggerUrl);
  const target = pages.find(page => String(page.id || page.targetId || "") === targetId);
  if (!target) throw new Error("PMS Setup's verified SkyTouch browser tab is no longer available");
  const parsed = new URL(target.url);
  if (parsed.protocol !== "https:" || !SKYTOUCH_HOSTS.has(parsed.hostname) || !parsed.pathname.startsWith("/pms/")) {
    throw new Error("PMS Setup's browser handoff is not on an approved SkyTouch page");
  }
  const client = new CDP(target.webSocketDebuggerUrl);
  await client.open();
  return client;
}

async function verifyHandoff(client, propertyCode) {
  const snapshot = await client.evaluate(`(() => ({url:location.href,text:document.body?.innerText||'',hasLogout:[...document.querySelectorAll('a,button')].some(e=>/^logout$/i.test((e.innerText||'').trim()))}))()`);
  const parsed = new URL(snapshot.url);
  if (parsed.protocol !== "https:" || !SKYTOUCH_HOSTS.has(parsed.hostname) || !parsed.pathname.startsWith("/pms/")) {
    throw new Error("The handed-off browser tab left SkyTouch");
  }
  if (!snapshot.hasLogout) throw new Error("The handed-off SkyTouch session is not authenticated");
  const labels = snapshot.text.split(/\r?\n/).map(line => line.trim()).filter(Boolean)
    .filter(line => /^[A-Za-z0-9][A-Za-z0-9_-]{1,23}\s+-\s+.+$/.test(line));
  if (labels.length !== 1 || !labels[0].toUpperCase().startsWith(`${propertyCode.toUpperCase()} - `)) {
    throw new Error("The handed-off SkyTouch property label does not match the requested hotel");
  }
}

async function openSearch(client, baseUrl) {
  const searchUrl = joinUrl(baseUrl, SEARCH_PATH);
  await client.goto(searchUrl);
  let ready = await client.evaluate(`!!document.querySelector('[name=searchLastName]')`);
  if (!ready) {
    throw new Error("SkyTouch reservation search form was not found; the page layout or permission may have changed");
  }
}

async function submitSearch(client, request) {
  await client.evaluate(pageScript(input => {
    const values = {
      searchLastName: input.last_name,
      searchFirstName: input.first_name,
      searchArrivalFromDate: input.arrival_from,
      searchArrivalToDate: input.arrival_to,
    };
    for (const [name, value] of Object.entries(values)) {
      const field = document.querySelector(`[name="${name}"]`);
      if (!field) throw new Error(`missing search field ${name}`);
      field.value = value;
      field.dispatchEvent(new Event('change', { bubbles: true }));
    }
    if (typeof window.lookUpProfileByAcctNo === 'function') window.lookUpProfileByAcctNo(true);
    else document.querySelector('[name=FindReservationSearchForm]')?.requestSubmit();
    return true;
  }, request));
  await new Promise(resolve => setTimeout(resolve, 500));
  await client.ready();
}

async function extractCandidates(client, baseUrl) {
  return await client.evaluate(pageScript(({ origin }) => {
    const clean = value => (value || '').replace(/\s+/g, ' ').trim();
    const key = value => clean(value).toLowerCase().replace(/[^a-z0-9]/g, '');
    const candidates = [];
    for (const table of document.querySelectorAll('table')) {
      const rows = [...table.querySelectorAll('tr')];
      if (rows.length < 2) continue;
      const headers = [...rows[0].querySelectorAll('th,td')].map(cell => key(cell.innerText));
      const accountIndex = headers.findIndex(h => h.includes('accountnumber') || h === 'account');
      if (accountIndex < 0) continue;
      for (const row of rows.slice(1)) {
        const cells = [...row.querySelectorAll('td')];
        if (!cells.length) continue;
        const get = (...names) => {
          const index = headers.findIndex(h => names.some(name => h.includes(name)));
          return index >= 0 ? clean(cells[index]?.innerText) : '';
        };
        const account = clean(cells[accountIndex]?.innerText);
        if (!account) continue;
        const link = row.querySelector('a[href]');
        candidates.push({ account_number: account, guest_name: get('guestname','name'), status:get('status'), arrival:get('arrival'), departure:get('departure'), href: link ? new URL(link.href, location.href).href : '' });
      }
    }
    if (!candidates.length && /reservation information/i.test(document.body?.innerText || '')) {
      const pairs = {};
      for (const row of document.querySelectorAll('tr')) {
        const cells = [...row.querySelectorAll('th,td')].map(cell => clean(cell.innerText));
        for (let i = 0; i + 1 < cells.length; i += 2) pairs[key(cells[i])] = cells[i + 1];
      }
      const account = pairs.accountnumber || pairs.account || '';
      if (account) candidates.push({ account_number: account, guest_name:pairs.guestname||pairs.name||'', status:pairs.status||'', arrival:pairs.arrival||'', departure:pairs.departure||'', href:location.href });
    }
    return candidates.filter(item => !item.href || new URL(item.href).origin === origin);
  }, { origin: new URL(baseUrl).origin }));
}

async function extractReservation(client, candidate, baseUrl) {
  if (candidate.href && candidate.href !== await client.evaluate("location.href")) await client.goto(assertSameOrigin(candidate.href, baseUrl));
  const details = await client.evaluate(`(() => {
    const clean=v=>(v||'').replace(/\s+/g,' ').trim(); const key=v=>clean(v).toLowerCase().replace(/[^a-z0-9]/g,''); const pairs={};
    for(const row of document.querySelectorAll('tr')){const cells=[...row.querySelectorAll('th,td')].map(c=>clean(c.innerText)); for(let i=0;i+1<cells.length;i+=2)pairs[key(cells[i])]=cells[i+1];}
    const folio=[...document.querySelectorAll('a[href],button')].find(e=>/guest folio/i.test(e.innerText||e.value||'') || /GuestFolio\.do/i.test(e.href||''));
    return {account_number:pairs.accountnumber||pairs.account||${JSON.stringify(candidate.account_number || "")},guest_name:pairs.guestname||pairs.name||${JSON.stringify(candidate.guest_name || "")},status:pairs.status||${JSON.stringify(candidate.status || "")},arrival:pairs.arrival||${JSON.stringify(candidate.arrival || "")},departure:pairs.departure||${JSON.stringify(candidate.departure || "")},folio_href:folio?.href||''};
  })()`);
  if (!details.folio_href) throw new Error(`Guest Folio link not found for account ${details.account_number}`);
  await client.goto(assertSameOrigin(details.folio_href, baseUrl));
  const folioOne = await client.evaluate(`(() => {const a=[...document.querySelectorAll('a[href]')].find(e=>/^\s*1\.\s*Folio 1\b/i.test(e.innerText||''));return a?.href||''})()`);
  if (folioOne) await client.goto(assertSameOrigin(folioOne, baseUrl));
  details.folio_1 = await client.evaluate(`(() => {
    const clean=v=>(v||'').replace(/\s+/g,' ').trim(); const key=v=>clean(v).toLowerCase().replace(/[^a-z0-9]/g,''); const out=[];
    for(const table of document.querySelectorAll('table')){const rows=[...table.querySelectorAll('tr')];if(rows.length<2)continue;const headers=[...rows[0].querySelectorAll('th,td')].map(c=>key(c.innerText));const di=headers.findIndex(h=>h==='description'),ci=headers.findIndex(h=>h==='comments'||h==='comment'),ai=headers.findIndex(h=>h==='amount');if(di<0||ai<0)continue;for(const row of rows.slice(1)){const cells=[...row.querySelectorAll('td')];if(!cells.length)continue;const raw=clean(cells[ai]?.innerText);if(!raw)continue;const negative=/^\(.*\)$/.test(raw);const numeric=raw.replace(/[^0-9.\-]/g,'');out.push({description:clean(cells[di]?.innerText),comments:ci>=0?clean(cells[ci]?.innerText):'',amount:(negative?'-':'')+numeric});}}
    return out;
  })()`);
  delete details.folio_href;
  return details;
}

async function handle(request) {
  if (!request.target_id || !request.property_code) throw new Error("verified SkyTouch handoff is required");
  const client = await connectPage(request.target_id);
  try {
    await verifyHandoff(client, request.property_code);
    await openSearch(client, SKYTOUCH_BASE_URL);
    if (request.action === "doctor") return { ok: true, authenticated: true, pms: "skytouch", property_code: request.property_code };
    if (request.action !== "search_reservations") throw new Error(`unsupported action ${request.action}`);
    await submitSearch(client, request);
    const candidates = await extractCandidates(client, SKYTOUCH_BASE_URL);
    const reservations = [];
    for (const candidate of candidates) reservations.push(await extractReservation(client, candidate, SKYTOUCH_BASE_URL));
    return { ok: true, reservations };
  } finally {
    client.close();
  }
}

try {
  const request = await readInput();
  const response = await handle(request);
  process.stdout.write(JSON.stringify(response));
} catch (error) {
  fail(error instanceof Error ? error.message : "unknown browser adapter failure");
}

