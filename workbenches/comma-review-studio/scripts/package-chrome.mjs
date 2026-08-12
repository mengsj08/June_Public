import { cp, mkdir, rm } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const projectRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const source = path.join(projectRoot, 'chrome-extension');
const destination = path.join(projectRoot, 'release', 'chrome-extension');

await rm(destination, { recursive: true, force: true });
await mkdir(path.dirname(destination), { recursive: true });
await cp(source, destination, { recursive: true });
await cp(path.join(projectRoot, 'dist'), path.join(destination, 'dist'), { recursive: true });

process.stdout.write(`${destination}\n`);
