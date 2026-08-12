import { access, readFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const projectRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const extensionRoot = path.join(projectRoot, 'release', 'chrome-extension');
const manifest = JSON.parse(await readFile(path.join(extensionRoot, 'manifest.json'), 'utf8'));

const expectedPermissions = ['activeTab', 'scripting', 'sidePanel', 'storage'];
const actualPermissions = [...(manifest.permissions || [])].sort();
if (JSON.stringify(actualPermissions) !== JSON.stringify([...expectedPermissions].sort())) {
  throw new Error(`Unexpected permissions: ${actualPermissions.join(', ')}`);
}
if ('host_permissions' in manifest || 'optional_host_permissions' in manifest) {
  throw new Error('Chrome wrapper must not declare persistent host permissions');
}
if (manifest.manifest_version !== 3) throw new Error('Manifest V3 is required');

const required = [
  manifest.background?.service_worker,
  manifest.side_panel?.default_path,
  'sidepanel.js',
  'sidepanel.css',
  'dist/comma-editor.js',
].filter(Boolean);
for (const relative of required) await access(path.join(extensionRoot, relative));

const html = await readFile(path.join(extensionRoot, 'sidepanel.html'), 'utf8');
if (/<script[^>]+src=["']https?:/i.test(html)) throw new Error('Remote scripts are forbidden in extension pages');

process.stdout.write(JSON.stringify({ ok: true, manifest: manifest.version, permissions: actualPermissions }) + '\n');
