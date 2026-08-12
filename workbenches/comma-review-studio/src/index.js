export * from './adapters/index.js';
export * from './core/index.js';
export * from './element/index.js';

import { registerCommaEditor } from './element/comma-editor.js';

if (typeof customElements !== 'undefined') registerCommaEditor();
