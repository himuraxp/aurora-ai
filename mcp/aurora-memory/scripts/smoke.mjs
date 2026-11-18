#!/usr/bin/env node
/**
 * Smoke test du bundle de distribution (ADR-025) : spawn, handshake MCP,
 * tools/list, surface attendue = 18 tools. N'accède JAMAIS aux données
 * (aucun tool call métier) — la connexion DB est inutile ici.
 *
 * Charge les mêmes candidats .env que migrate.mjs (le serveur valide
 * DATABASE_URL au démarrage), puis spawn le bundle avec l'environnement hérité.
 *
 * Usage : node scripts/smoke.mjs   (exit 0 = sain)
 */
import { spawn } from 'node:child_process';
import { existsSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { join, dirname } from 'node:path';
import dotenv from 'dotenv';

const serverRoot = dirname(dirname(fileURLToPath(import.meta.url)));
const configRoot = dirname(fileURLToPath(new URL('../../../', import.meta.url)));

dotenv.config({ path: join(configRoot, '.env') });

const BUNDLE = join(serverRoot, 'dist', 'index.mjs');
if (!existsSync(BUNDLE)) {
  console.error(`[smoke] bundle absent : ${BUNDLE} (npm run build:mcp)`);
  process.exit(1);
}

const EXPECTED_TOOLS = 18;
const PROTOCOL_VERSION = '2024-11-05';

const proc = spawn('node', [BUNDLE], { stdio: ['pipe', 'pipe', 'pipe'] });
let stdout = Buffer.alloc(0);
let stderr = '';

proc.stderr.on('data', (d) => { stderr += d.toString(); });
proc.stdin.on('error', () => { /* EPIPE si le bundle meurt en cours d'écriture — l'exit handler fait le diagnostic */ });
proc.stdin.write(JSON.stringify({
  jsonrpc: '2.0', id: 1, method: 'initialize',
  params: { protocolVersion: PROTOCOL_VERSION, capabilities: {}, clientInfo: { name: 'aurora-memory-smoke', version: '1.0.0' } },
}) + '\n');

const exit = (code, message) => {
  try { proc.kill('SIGTERM'); } catch { /* déjà sorti */ }
  const killFallback = setTimeout(() => {
    try { proc.kill('SIGKILL'); } catch { /* déjà sorti */ }
  }, 300);
  killFallback.unref();
  if (message) console.error(message);
  process.exit(code);
};

const timer = setTimeout(() => exit(1, `[smoke] timeout : pas de réponse du bundle`), 15_000);

const parseLines = () => {
  for (;;) {
    const nl = stdout.indexOf('\n');
    if (nl === -1) return;
    const line = stdout.subarray(0, nl).toString().trim();
    stdout = stdout.subarray(nl + 1);
    if (!line) continue;
    let msg;
    try { msg = JSON.parse(line); } catch { return exit(1, `[smoke] payload JSON invalide : ${line.slice(0, 80)}`); }
    if (msg.id === 1) {
      // handshake aligné sur le bridge : notification initialized avant tools/list
      proc.stdin.write(JSON.stringify({ jsonrpc: '2.0', method: 'notifications/initialized' }) + '\n');
      proc.stdin.write(JSON.stringify({ jsonrpc: '2.0', id: 2, method: 'tools/list' }) + '\n');
    }
    if (msg.id === 2) {
      clearTimeout(timer);
      const names = (msg.result?.tools ?? []).map((t) => t.name);
      const lessons = names.filter((n) => n.startsWith('lesson_')).length;
      if (names.length !== EXPECTED_TOOLS) {
        return exit(1, `[smoke] surface inattendue : ${names.length} tools (attendu ${EXPECTED_TOOLS})`);
      }
      if (lessons !== 3) {
        return exit(1, `[smoke] surface lesson_* incomplète : ${lessons}/3`);
      }
      console.log(`[smoke] OK : ${names.length} tools dont lesson_* ×${lessons} — bundle ${BUNDLE}`);
      exit(0);
    }
  }
};
proc.stdout.on('data', (d) => { stdout = Buffer.concat([stdout, d]); parseLines(); });
proc.on('exit', () => exit(1, `[smoke] le bundle s'est arrêté avant tools/list${stderr ? ` — stderr : ${stderr.trim().slice(0, 300)}` : ''}`));
